import asyncio
from typing import List, Dict, Any, Optional, Callable
from openai import AsyncOpenAI

from config import Config
from prompts import (
    get_summary_prompt,
    get_memory_update_prompt,
    get_complete_memory_json_prompt,
)
from prompts.system import get_cacheable_system_prompt, get_current_time_str
from utils.logger import get_logger

logger = get_logger()


class LLMClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        chat_model: Optional[str] = None,
        tool_model: Optional[str] = None,
    ):
        self.api_key = api_key or Config.OPENAI_API_KEY
        self.api_base = api_base or Config.OPENAI_API_BASE
        self.chat_model = chat_model or Config.CHAT_MODEL
        self.tool_model = tool_model or Config.TOOL_MODEL

        self._chat_client: Optional[AsyncOpenAI] = None
        self._tool_client: Optional[AsyncOpenAI] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        self._tools_cache: Optional[List[Dict[str, Any]]] = None
        self._tool_executor: Optional[Callable] = None

    def _get_event_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        return self._loop

    def _ensure_chat_client_initialized(self) -> None:
        if self._chat_client is None:
            self._chat_client = AsyncOpenAI(
                api_key=self.api_key, base_url=self.api_base
            )
            logger.info(f"Initialized ChatClient: {self.chat_model}")

    def _ensure_tool_client_initialized(self) -> None:
        if self._tool_client is None:
            self._tool_client = AsyncOpenAI(
                api_key=self.api_key, base_url=self.api_base
            )
            logger.info(f"Initialized ToolClient: {self.tool_model}")

    def set_tool_executor(self, executor: Callable) -> None:
        self._tool_executor = executor
        logger.info("Tool executor registered")

    def set_tools(self, tools: List[Dict[str, Any]]) -> None:
        self._tools_cache = tools
        logger.info(f"Tools registered: {len(tools)} tools")

    def _get_tools(self) -> Optional[List[Dict[str, Any]]]:
        return self._tools_cache

    async def _async_chat(
        self,
        messages: List[Dict[str, str]],
        use_tools: bool = True,
        force_chat_model: bool = False,
    ) -> Dict[str, Any]:
        """Internal async chat method.

        Args:
            messages: Chat messages
            use_tools: Whether to include tools in the request
            force_chat_model: If True, always use chat_model even when tools are available
        """
        # Ensure client is initialized BEFORE getting the reference
        if force_chat_model:
            # Always use chat_model when forced (e.g., for regular conversation)
            self._ensure_chat_client_initialized()
            client = self._chat_client
            model = self.chat_model
        elif use_tools and self._get_tools():
            self._ensure_tool_client_initialized()
            client = self._tool_client
            model = self.tool_model
        else:
            self._ensure_chat_client_initialized()
            client = self._chat_client
            model = self.chat_model

        try:
            params: Dict[str, Any] = {"model": model, "messages": messages}

            if use_tools:
                tools = self._get_tools()
                if tools:
                    params["tools"] = tools
                    if Config.DEBUG_SHOW_FULL_PROMPT:
                        logger.debug(f"Including {len(tools)} tools in request")
                        for tool in tools:
                            logger.debug(
                                f"  - {tool['function']['name']}: {tool['function']['description']}"
                            )

            if Config.DEBUG_SHOW_FULL_PROMPT:
                logger.debug(f"Full prompt sent to LLM (model={model}):\n{messages}")

            response = await client.chat.completions.create(**params)

            message = response.choices[0].message

            result = {
                "content": message.content or "",
                "tool_calls": None,
                "reasoning_content": None,
            }

            # Extract reasoning content if present (for o1/o3 models)
            if hasattr(message, "reasoning_content") and message.reasoning_content:
                result["reasoning_content"] = message.reasoning_content
                if Config.DEBUG_SHOW_FULL_PROMPT:
                    logger.debug(
                        f"Model reasoning: {message.reasoning_content[:200]}..."
                    )

            if message.tool_calls:
                result["tool_calls"] = [
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                    for tc in message.tool_calls
                ]

            return result

        except Exception as e:
            logger.error(f"LLM chat failed: {e}")
            raise

    def chat(
        self,
        current_context: List[Dict[str, str]],
        retrieved_summaries: List[str],
        retrieved_conversations: List[str],
        recent_summaries: Optional[List[str]] = None,
    ) -> str:
        """Synchronous wrapper for chat. Use chat_async in async contexts."""
        try:
            # Check if we're in an event loop
            loop = asyncio.get_running_loop()
            # If we get here, we're in an async context - this shouldn't be called
            raise RuntimeError(
                "chat() called from async context. Use await chat_async() instead."
            )
        except RuntimeError as e:
            if "no running event loop" in str(e).lower():
                # We're in sync context, safe to use run_until_complete
                messages = self._build_chat_messages(
                    current_context,
                    retrieved_summaries,
                    retrieved_conversations,
                    recent_summaries,
                )

                loop = self._get_event_loop()

                async def chat_with_tools() -> str:
                    # Always use chat_model for conversation, even when tools are available
                    result = await self._async_chat(
                        messages, use_tools=True, force_chat_model=True
                    )

                    while result["tool_calls"]:
                        if self._tool_executor is None:
                            logger.warning("Tool calls but no executor registered")
                            break

                        tool_responses = []
                        for call in result["tool_calls"]:
                            logger.info(f"Executing tool: {call['name']}")
                            try:
                                # Check if tool executor is async
                                response = self._tool_executor(
                                    call["name"], call["arguments"]
                                )
                                # If it's a coroutine, await it
                                if asyncio.iscoroutine(response):
                                    response = await response
                                tool_responses.append(
                                    {
                                        "tool_call_id": call["id"],
                                        "role": "tool",
                                        "content": str(response),
                                    }
                                )
                            except Exception as e:
                                logger.error(f"Tool execution failed: {e}")
                                tool_responses.append(
                                    {
                                        "tool_call_id": call["id"],
                                        "role": "tool",
                                        "content": f"Error: {str(e)}",
                                    }
                                )

                        # Build assistant message with reasoning content if present
                        assistant_message = {
                            "role": "assistant",
                            "content": result["content"] or "",
                        }

                        # Include reasoning content for o1/o3 models
                        if result.get("reasoning_content"):
                            assistant_message["reasoning_content"] = result[
                                "reasoning_content"
                            ]

                        # Include tool calls
                        if result["tool_calls"]:
                            assistant_message["tool_calls"] = result["tool_calls"]

                        messages.append(assistant_message)
                        messages.extend(tool_responses)

                        # Continue using chat_model for subsequent requests
                        result = await self._async_chat(
                            messages, use_tools=True, force_chat_model=True
                        )

                    return result["content"]

                return loop.run_until_complete(chat_with_tools())
            else:
                raise

    async def chat_async(
        self,
        current_context: List[Dict[str, str]],
        retrieved_summaries: List[str],
        retrieved_conversations: List[str],
        recent_summaries: Optional[List[str]] = None,
    ) -> str:
        """Async version of chat. Use this in async contexts.

        Always uses chat_model for conversation, even when tools are available.
        """
        messages = self._build_chat_messages(
            current_context,
            retrieved_summaries,
            retrieved_conversations,
            recent_summaries,
        )

        # Always use chat_model for conversation
        result = await self._async_chat(messages, use_tools=True, force_chat_model=True)

        while result["tool_calls"]:
            if self._tool_executor is None:
                logger.warning("Tool calls but no executor registered")
                break

            tool_responses = []
            for call in result["tool_calls"]:
                logger.info(f"Executing tool: {call['name']}")
                try:
                    # Check if tool executor is async
                    response = self._tool_executor(call["name"], call["arguments"])
                    # If it's a coroutine, await it
                    if asyncio.iscoroutine(response):
                        response = await response
                    tool_responses.append(
                        {
                            "tool_call_id": call["id"],
                            "role": "tool",
                            "content": str(response),
                        }
                    )
                except Exception as e:
                    logger.error(f"Tool execution failed: {e}")
                    tool_responses.append(
                        {
                            "tool_call_id": call["id"],
                            "role": "tool",
                            "content": f"Error: {str(e)}",
                        }
                    )

            # Build assistant message with reasoning content if present
            assistant_message = {
                "role": "assistant",
                "content": result["content"] or "",
            }

            # Include reasoning content for o1/o3 models
            if result.get("reasoning_content"):
                assistant_message["reasoning_content"] = result["reasoning_content"]

            # Include tool calls
            if result["tool_calls"]:
                assistant_message["tool_calls"] = result["tool_calls"]

            messages.append(assistant_message)
            messages.extend(tool_responses)

            # Continue using chat_model
            result = await self._async_chat(
                messages, use_tools=True, force_chat_model=True
            )

        return result["content"]

    async def chat_with_custom_message_async(
        self,
        current_context: List[Dict[str, str]],
        retrieved_summaries: List[str],
        retrieved_conversations: List[str],
        recent_summaries: Optional[List[str]] = None,
        custom_user_message: Optional[str] = None,
    ) -> str:
        """Async chat with custom user message instead of context's last message.

        This is useful for scheduled tasks where the triggering message should not
        be saved to memory but still needs to be processed by the LLM.

        Args:
            current_context: Current conversation history (without the message to be processed)
            retrieved_summaries: Retrieved historical summaries
            retrieved_conversations: Retrieved historical conversations
            recent_summaries: Recent conversation summaries (max 3)
            custom_user_message: Custom user message to append at the end

        Returns:
            Bot's response
        """
        messages = self._build_chat_messages(
            current_context,
            retrieved_summaries,
            retrieved_conversations,
            recent_summaries,
            custom_user_message=custom_user_message,
        )

        # Always use chat_model for conversation
        result = await self._async_chat(messages, use_tools=True, force_chat_model=True)

        while result["tool_calls"]:
            if self._tool_executor is None:
                logger.warning("Tool calls but no executor registered")
                break

            tool_responses = []
            for call in result["tool_calls"]:
                logger.info(f"Executing tool: {call['name']}")
                try:
                    # Check if tool executor is async
                    response = self._tool_executor(call["name"], call["arguments"])
                    # If it's a coroutine, await it
                    if asyncio.iscoroutine(response):
                        response = await response
                    tool_responses.append(
                        {
                            "tool_call_id": call["id"],
                            "role": "tool",
                            "content": str(response),
                        }
                    )
                except Exception as e:
                    logger.error(f"Tool execution failed: {e}")
                    tool_responses.append(
                        {
                            "tool_call_id": call["id"],
                            "role": "tool",
                            "content": f"Error: {str(e)}",
                        }
                    )

            # Build assistant message with reasoning content if present
            assistant_message = {
                "role": "assistant",
                "content": result["content"] or "",
            }

            # Include reasoning content for o1/o3 models
            if result.get("reasoning_content"):
                assistant_message["reasoning_content"] = result["reasoning_content"]

            # Include tool calls
            if result["tool_calls"]:
                assistant_message["tool_calls"] = result["tool_calls"]

            messages.append(assistant_message)
            messages.extend(tool_responses)

            # Continue using chat_model
            result = await self._async_chat(
                messages, use_tools=True, force_chat_model=True
            )

        return result["content"]

    def _build_chat_messages(
        self,
        current_context: List[Dict[str, str]],
        retrieved_summaries: List[str],
        retrieved_conversations: List[str],
        recent_summaries: Optional[List[str]] = None,
        custom_user_message: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """Build messages with optimized structure for prompt caching.

        Message order (for optimal implicit caching):
        1. Main system prompt (static instructions + bot + user + events + commands + recent summaries)
           → This forms a single large cacheable block
        2. Current conversation history (user/assistant, excluding last user message)
        3. Retrieved historical summaries (system, if any)
        4. Retrieved historical conversations (system, if any)
        5. Current time (system)
        6. Current user input (user) - emphasized at the end

        Args:
            current_context: Current conversation messages (used if custom_user_message is None)
            retrieved_summaries: Retrieved historical summaries
            retrieved_conversations: Retrieved historical conversations
            recent_summaries: Recent conversation summaries (max 3)
            custom_user_message: Optional custom user message to append instead of context's last message
        """
        messages = []

        # 1. Main system prompt (single large cacheable block)
        messages.append(
            {"role": "system", "content": get_cacheable_system_prompt(recent_summaries)}
        )

        # 2. Current conversation history (excluding last user message)
        if current_context:
            history = current_context[:-1]
            messages.append(
                {
                    "role": "system",
                    "content": "BEGINNING OF THE CURRENT CONVERSATION.",
                }
            )
            messages.extend(history)
            messages.append(
                {
                    "role": "system",
                    "content": "END OF THE CURRENT CONVERSATION.",
                }
            )

        # 3. Retrieved historical summaries (if any)
        if retrieved_summaries:
            messages.append(
                {
                    "role": "system",
                    "content": "## Related Historical Summaries\n\n"
                    + "\n\n".join(retrieved_summaries),
                }
            )

        # 4. Retrieved historical conversations (if any)
        if retrieved_conversations:
            messages.append(
                {
                    "role": "system",
                    "content": "## Related Historical Conversations\n\n"
                    + "\n\n".join(retrieved_conversations),
                }
            )

        # 5. Current time
        messages.append(
            {
                "role": "system",
                "content": f"END OF ALL CONTEXT.\n\n**Current Time**: {get_current_time_str()}",
            }
        )

        # 6. Current user input (emphasize at the end)
        if custom_user_message:
            # Use custom user message (e.g., for scheduled tasks)
            emphasized_message = {
                "role": "user",
                "content": f"Please respond to the above request based on all context provided.\n\n⚡ [Current Request]\n{custom_user_message}",
            }
            messages.append(emphasized_message)
        elif current_context:
            current_user_message = current_context[-1]
            # Add emphasis to highlight this is the current request
            emphasized_message = {
                "role": current_user_message["role"],
                "content": f"Please respond to the above request based on all context provided.\n\n⚡ [Current Request]\n{current_user_message['content']}",
            }
            messages.append(emphasized_message)

        return messages

    def generate_summary(
        self, existing_summary: Optional[str], new_conversations: List[Dict[str, str]]
    ) -> str:
        conv_text = "\n".join(
            [
                f"{msg['role']}: {msg.get('content', msg.get('text', ''))}"
                for msg in new_conversations
            ]
        )

        prompt = get_summary_prompt(existing_summary, conv_text)

        loop = self._get_event_loop()

        async def get_summary() -> str:
            self._ensure_tool_client_initialized()

            if Config.DEBUG_SHOW_FULL_PROMPT:
                logger.debug(
                    f"Summary prompt sent to tool_model ({self.tool_model}):\n{prompt}"
                )

            response = await self._tool_client.chat.completions.create(
                model=self.tool_model,
                messages=[
                    {"role": "system", "content": "You are a conversation summarizer."},
                    {"role": "user", "content": prompt},
                ],
            )

            result = response.choices[0].message.content or ""
            if Config.DEBUG_SHOW_FULL_PROMPT:
                logger.debug(f"Summary result from tool_model:\n{result}")
            return result

        try:
            return loop.run_until_complete(get_summary())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(get_summary())

    async def generate_summary_async(
        self, existing_summary: Optional[str], new_conversations: List[Dict[str, str]]
    ) -> str:
        """Async version of generate_summary. Use this in async contexts."""
        conv_text = "\n".join(
            [
                f"{msg['role']}: {msg.get('content', msg.get('text', ''))}"
                for msg in new_conversations
            ]
        )

        prompt = get_summary_prompt(existing_summary, conv_text)

        self._ensure_tool_client_initialized()

        if Config.DEBUG_SHOW_FULL_PROMPT:
            logger.debug(
                f"Summary (async) prompt sent to tool_model ({self.tool_model}):\n{prompt}"
            )

        response = await self._tool_client.chat.completions.create(
            model=self.tool_model,
            messages=[
                {"role": "system", "content": "You are a conversation summarizer."},
                {"role": "user", "content": prompt},
            ],
        )

        result = response.choices[0].message.content or ""
        if Config.DEBUG_SHOW_FULL_PROMPT:
            logger.debug(f"Summary (async) result from tool_model:\n{result}")
        return result

    def generate_memory_update(
        self,
        messages: List[Dict[str, str]],
        current_seele_json: str,
        first_timestamp: Optional[int] = None,
        last_timestamp: Optional[int] = None,
    ) -> str:
        """Synchronous wrapper for generate_memory_update. Use generate_memory_update_async in async contexts."""
        conv_text = "\n".join(
            [
                f"{msg['role']}: {msg.get('content', msg.get('text', ''))}"
                for msg in messages
            ]
        )

        prompt = get_memory_update_prompt(
            conv_text, current_seele_json, first_timestamp, last_timestamp
        )

        try:
            # Check if we're in an event loop
            loop = asyncio.get_running_loop()
            # If we get here, we're in an async context - this shouldn't be called
            raise RuntimeError(
                "generate_memory_update() called from async context. Use await generate_memory_update_async() instead."
            )
        except RuntimeError as e:
            if "no running event loop" in str(e).lower():
                # We're in sync context, safe to use run_until_complete
                loop = self._get_event_loop()

                async def get_update() -> str:
                    self._ensure_tool_client_initialized()

                    if Config.DEBUG_SHOW_FULL_PROMPT:
                        logger.debug(
                            f"Memory update prompt sent to tool_model ({self.tool_model}):\n{prompt}"
                        )

                    response = await self._tool_client.chat.completions.create(
                        model=self.tool_model,
                        messages=[
                            {
                                "role": "system",
                                "content": "You generate JSON patches for memory updates.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                    )

                    result = response.choices[0].message.content or ""
                    if Config.DEBUG_SHOW_FULL_PROMPT:
                        logger.debug(f"Memory update result from tool_model:\n{result}")
                    return result

                return loop.run_until_complete(get_update())
            else:
                raise

    async def generate_memory_update_async(
        self,
        messages: List[Dict[str, str]],
        current_seele_json: str,
        first_timestamp: Optional[int] = None,
        last_timestamp: Optional[int] = None,
    ) -> str:
        """Async version of generate_memory_update. Use this in async contexts."""
        conv_text = "\n".join(
            [
                f"{msg['role']}: {msg.get('content', msg.get('text', ''))}"
                for msg in messages
            ]
        )

        prompt = get_memory_update_prompt(
            conv_text, current_seele_json, first_timestamp, last_timestamp
        )

        self._ensure_tool_client_initialized()

        if Config.DEBUG_SHOW_FULL_PROMPT:
            logger.debug(
                f"Memory update (async) prompt sent to tool_model ({self.tool_model}):\n{prompt}"
            )

        response = await self._tool_client.chat.completions.create(
            model=self.tool_model,
            messages=[
                {
                    "role": "system",
                    "content": "You generate JSON patches for memory updates.",
                },
                {"role": "user", "content": prompt},
            ],
        )

        result = response.choices[0].message.content or ""
        if Config.DEBUG_SHOW_FULL_PROMPT:
            logger.debug(f"Memory update (async) result from tool_model:\n{result}")
        return result

    def generate_complete_memory_json(
        self,
        messages: List[Dict[str, str]],
        current_seele_json: str,
        error_message: str,
        first_timestamp: Optional[int] = None,
        last_timestamp: Optional[int] = None,
    ) -> str:
        """Synchronous wrapper for generating complete seele.json. Use generate_complete_memory_json_async in async contexts."""
        conv_text = "\n".join(
            [
                f"{msg['role']}: {msg.get('content', msg.get('text', ''))}"
                for msg in messages
            ]
        )

        prompt = get_complete_memory_json_prompt(
            conv_text,
            current_seele_json,
            error_message,
            first_timestamp,
            last_timestamp,
        )

        try:
            # Check if we're in an event loop
            loop = asyncio.get_running_loop()
            # If we get here, we're in an async context - this shouldn't be called
            raise RuntimeError(
                "generate_complete_memory_json() called from async context. Use await generate_complete_memory_json_async() instead."
            )
        except RuntimeError as e:
            if "no running event loop" in str(e).lower():
                # We're in sync context, safe to use run_until_complete
                loop = self._get_event_loop()

                async def get_complete_json() -> str:
                    self._ensure_tool_client_initialized()

                    if Config.DEBUG_SHOW_FULL_PROMPT:
                        logger.debug(
                            f"Complete memory JSON prompt sent to tool_model ({self.tool_model}):\n{prompt}"
                        )

                    response = await self._tool_client.chat.completions.create(
                        model=self.tool_model,
                        messages=[
                            {
                                "role": "system",
                                "content": "You generate complete seele.json objects for memory updates.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                    )

                    result = response.choices[0].message.content or ""
                    if Config.DEBUG_SHOW_FULL_PROMPT:
                        logger.debug(
                            f"Complete memory JSON result from tool_model:\n{result}"
                        )
                    return result

                return loop.run_until_complete(get_complete_json())
            else:
                raise

    async def generate_complete_memory_json_async(
        self,
        messages: List[Dict[str, str]],
        current_seele_json: str,
        error_message: str,
        first_timestamp: Optional[int] = None,
        last_timestamp: Optional[int] = None,
    ) -> str:
        """Async version of generate_complete_memory_json. Use this in async contexts."""
        conv_text = "\n".join(
            [
                f"{msg['role']}: {msg.get('content', msg.get('text', ''))}"
                for msg in messages
            ]
        )

        prompt = get_complete_memory_json_prompt(
            conv_text,
            current_seele_json,
            error_message,
            first_timestamp,
            last_timestamp,
        )

        self._ensure_tool_client_initialized()

        if Config.DEBUG_SHOW_FULL_PROMPT:
            logger.debug(
                f"Complete memory JSON (async) prompt sent to tool_model ({self.tool_model}):\n{prompt}"
            )

        response = await self._tool_client.chat.completions.create(
            model=self.tool_model,
            messages=[
                {
                    "role": "system",
                    "content": "You generate complete seele.json objects for memory updates.",
                },
                {"role": "user", "content": prompt},
            ],
        )

        result = response.choices[0].message.content or ""
        if Config.DEBUG_SHOW_FULL_PROMPT:
            logger.debug(
                f"Complete memory JSON (async) result from tool_model:\n{result}"
            )
        return result

    async def _async_close(self) -> None:
        if self._chat_client is not None:
            await self._chat_client.close()
            self._chat_client = None
        if self._tool_client is not None:
            await self._tool_client.close()
            self._tool_client = None

    def close(self) -> None:
        """Synchronous wrapper for close. Use close_async in async contexts."""
        try:
            # Check if we're in an event loop
            loop = asyncio.get_running_loop()
            # If we get here, we're in an async context - this shouldn't be called
            raise RuntimeError(
                "close() called from async context. Use await close_async() instead."
            )
        except RuntimeError as e:
            if "no running event loop" in str(e).lower():
                # We're in sync context, safe to use run_until_complete
                loop = self._get_event_loop()
                if not loop.is_closed():
                    loop.run_until_complete(self._async_close())
            else:
                raise

    async def close_async(self) -> None:
        """Async version of close. Use this in async contexts."""
        await self._async_close()
