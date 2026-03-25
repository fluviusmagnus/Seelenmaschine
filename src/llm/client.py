import asyncio
import re
from typing import List, Dict, Any, Optional, Callable, Awaitable

from openai import AsyncOpenAI

from config import Config
from prompts import (
    get_summary_prompt,
    get_memory_update_prompt,
    get_complete_memory_json_prompt,
)
from prompts.system import (
    get_cacheable_system_prompt,
    get_current_time_str,
    load_seele_json,
)
from utils.logger import get_logger

logger = get_logger()


class LLMClient:
    _MAX_TOOL_RESPONSE_CHARS = 12000
    _BASE64_SEQUENCE_PATTERN = re.compile(r"[A-Za-z0-9+/=]{512,}")

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

    @staticmethod
    def _preview_text(text: Optional[str], max_length: int = 120) -> str:
        """Build a compact single-line preview for logs."""
        if text is None:
            return ""

        normalized = " ".join(str(text).split())
        if len(normalized) <= max_length:
            return normalized
        return f"{normalized[:max_length]}..."

    def _get_tool_names(self) -> List[str]:
        """Return currently registered tool names for diagnostics."""
        tools = self._get_tools() or []
        tool_names: List[str] = []

        for tool in tools:
            function = tool.get("function", {})
            name = function.get("name")
            if name:
                tool_names.append(str(name))

        return tool_names

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
        tool_names = self._get_tool_names()
        logger.info(f"Tools registered: {len(tools)} tools")
        if tool_names:
            logger.debug(f"Registered tool names: {tool_names}")

    def _get_tools(self) -> Optional[List[Dict[str, Any]]]:
        return self._tools_cache

    def _get_display_name_for_role(self, role: str) -> str:
        """Map internal conversation roles to display names from seele.json."""
        seele_data = load_seele_json()
        bot_name = seele_data.get("bot", {}).get("name", "AI Assistant")
        user_name = seele_data.get("user", {}).get("name", "User")

        role_to_name = {
            "user": user_name,
            "assistant": bot_name,
        }
        return role_to_name.get(role, role)

    def _format_conversation_messages(self, messages: List[Dict[str, str]]) -> str:
        """Format conversation messages using user/bot names instead of raw roles."""
        return "\n".join(
            [
                f"{self._get_display_name_for_role(msg['role'])}: {msg.get('content', msg.get('text', ''))}"
                for msg in messages
            ]
        )

    def _format_tool_calls_for_api(self, tool_calls: List[Any]) -> List[Dict[str, Any]]:
        """Convert SDK tool call objects to OpenAI API message format."""
        formatted_tool_calls: List[Dict[str, Any]] = []

        for tool_call in tool_calls:
            function = getattr(tool_call, "function", None)
            tool_call_id = getattr(tool_call, "id", None)
            tool_call_type = getattr(tool_call, "type", None) or "function"
            function_name = getattr(function, "name", None)
            function_arguments = getattr(function, "arguments", None)

            if not tool_call_id or not function_name:
                logger.warning(f"Skipping invalid tool call from model: {tool_call}")
                continue

            formatted_tool_calls.append(
                {
                    "id": tool_call_id,
                    "type": tool_call_type,
                    "function": {
                        "name": function_name,
                        "arguments": function_arguments or "{}",
                    },
                }
            )

        return formatted_tool_calls

    def _sanitize_tool_response_for_prompt(self, response: Any) -> str:
        """Sanitize tool output before appending it back into the LLM context."""
        text = str(response)
        if not text:
            return ""

        base64_match = self._find_base64_like_sequence(text)
        if base64_match is not None:
            return (
                "[tool output omitted: detected large base64/binary-like payload "
                f"of length ≈ {len(base64_match)}]"
            )

        if len(text) <= self._MAX_TOOL_RESPONSE_CHARS:
            return text

        omitted_chars = len(text) - self._MAX_TOOL_RESPONSE_CHARS
        head = text[:6000].rstrip()
        tail = text[-2000:].lstrip()
        return (
            f"{head}\n\n"
            f"[tool output truncated, omitted {omitted_chars} characters]\n\n"
            f"{tail}"
        )

    def _find_base64_like_sequence(self, text: str) -> Optional[str]:
        """Return a suspicious base64-like sequence if one is found."""
        for match in self._BASE64_SEQUENCE_PATTERN.finditer(text):
            candidate = match.group(0)
            if self._looks_like_base64_payload(candidate):
                return candidate
        return None

    def _looks_like_base64_payload(self, candidate: str) -> bool:
        """Heuristic to avoid misclassifying long plain text as base64."""
        if len(candidate) < 512:
            return False

        if not any(ch in candidate for ch in "+/="):
            return False

        distinct_chars = len(set(candidate))
        if distinct_chars < 8:
            return False

        return True

    def _format_llm_exception(self, error: Exception) -> str:
        """Build a readable error message from OpenAI/transport exceptions."""
        error_type = type(error).__name__
        error_text = str(error).strip() or repr(error)

        body = getattr(error, "body", None)
        if isinstance(body, dict):
            error_payload = body.get("error")
            if isinstance(error_payload, dict):
                message = error_payload.get("message")
                code = error_payload.get("code")
                if message:
                    code_suffix = f" (code={code})" if code is not None else ""
                    return f"{error_type}: {message}{code_suffix}"

        response = getattr(error, "response", None)
        if response is not None:
            status_code = getattr(response, "status_code", None)
            if status_code is not None:
                return f"{error_type}: HTTP {status_code} - {error_text}"

        return f"{error_type}: {error_text}"

    def _build_assistant_message_from_result(
        self, result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build an assistant message compatible with OpenAI tool calling."""
        assistant_message: Dict[str, Any] = {
            "role": "assistant",
            "content": result.get("content") or "",
        }

        if result.get("reasoning_content"):
            assistant_message["reasoning_content"] = result["reasoning_content"]

        if result.get("api_tool_calls"):
            assistant_message["tool_calls"] = result["api_tool_calls"]

        return assistant_message

    def _extract_assistant_text_from_result(
        self, result: Dict[str, Any]
    ) -> Optional[str]:
        """Extract assistant text content that should be treated as a normal message."""
        content = result.get("content")
        if content is None:
            return None

        content_str = str(content)
        if not content_str.strip():
            return None

        return content_str

    async def _run_chat_with_tool_loop(
        self,
        messages: List[Dict[str, str]],
        intermediate_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        """Run chat completion loop with tool execution and collect assistant texts."""
        assistant_messages: List[str] = []
        iteration = 1

        # Always use chat_model for conversation
        result = await self._async_chat(messages, use_tools=True, force_chat_model=True)

        while result["tool_calls"]:
            logger.info(
                f"LLM tool loop iteration {iteration}: received {len(result['tool_calls'])} tool call(s)"
            )
            assistant_text = self._extract_assistant_text_from_result(result)
            if assistant_text:
                assistant_messages.append(assistant_text)
                logger.info(
                    "LLM emitted intermediate assistant text before tool execution: "
                    f"{self._preview_text(assistant_text)}"
                )
                if intermediate_callback:
                    await intermediate_callback(assistant_text)

            if self._tool_executor is None:
                logger.warning("Tool calls but no executor registered")
                break

            tool_responses = []
            for call in result["tool_calls"]:
                logger.info(f"Executing tool: {call['name']}")
                try:
                    response = self._tool_executor(call["name"], call["arguments"])
                    if asyncio.iscoroutine(response):
                        response = await response
                    sanitized_response = self._sanitize_tool_response_for_prompt(
                        response
                    )
                    logger.info(
                        f"Tool '{call['name']}' completed with response preview: "
                        f"{self._preview_text(sanitized_response)}"
                    )
                    tool_responses.append(
                        {
                            "tool_call_id": call["id"],
                            "role": "tool",
                            "content": sanitized_response,
                        }
                    )
                except Exception as e:
                    error_text = f"{type(e).__name__}: {e}"
                    logger.error(f"Tool execution failed: {error_text}")
                    tool_responses.append(
                        {
                            "tool_call_id": call["id"],
                            "role": "tool",
                            "content": f"Error: {error_text}",
                        }
                    )

            assistant_message = self._build_assistant_message_from_result(result)
            messages.append(assistant_message)
            messages.extend(tool_responses)

            result = await self._async_chat(
                messages, use_tools=True, force_chat_model=True
            )
            iteration += 1

        final_text = self._extract_assistant_text_from_result(result) or ""
        if final_text:
            assistant_messages.append(final_text)

        logger.info(
            "LLM tool loop finished: "
            f"assistant_messages={len(assistant_messages)}, final_text={self._preview_text(final_text)}"
        )

        return {
            "final_text": final_text,
            "assistant_messages": assistant_messages,
        }

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
            included_tool_names: List[str] = []

            if use_tools:
                tools = self._get_tools()
                if tools:
                    params["tools"] = tools
                    included_tool_names = self._get_tool_names()
                    if Config.DEBUG_SHOW_FULL_PROMPT:
                        logger.debug(f"Including {len(tools)} tools in request")
                        for tool in tools:
                            logger.debug(
                                f"  - {tool['function']['name']}: {tool['function']['description']}"
                            )

            logger.info(
                "Sending LLM request: "
                f"model={model}, messages={len(messages)}, tools={included_tool_names or []}"
            )

            if Config.DEBUG_SHOW_FULL_PROMPT:
                logger.debug(f"Full prompt sent to LLM (model={model}):\n{messages}")

            response = await client.chat.completions.create(**params)

            message = response.choices[0].message

            result = {
                "content": message.content or "",
                "tool_calls": None,
                "api_tool_calls": None,
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
                result["api_tool_calls"] = self._format_tool_calls_for_api(
                    message.tool_calls
                )
                result["tool_calls"] = [
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                    for tc in message.tool_calls
                    if getattr(tc, "id", None)
                    and getattr(getattr(tc, "function", None), "name", None)
                ]

                if not result["tool_calls"]:
                    result["tool_calls"] = None
                if not result["api_tool_calls"]:
                    result["api_tool_calls"] = None

            if result["tool_calls"]:
                tool_names = [call["name"] for call in result["tool_calls"]]
                logger.info(
                    f"LLM response contains {len(tool_names)} tool call(s): {tool_names}"
                )
            else:
                logger.info("LLM response contains no tool calls")

            if result["content"]:
                logger.debug(
                    "LLM response content preview: "
                    f"{self._preview_text(result['content'])}"
                )

            return result

        except Exception as e:
            error_message = self._format_llm_exception(e)
            logger.error(f"LLM chat failed: {error_message}", exc_info=True)
            raise RuntimeError(error_message) from e

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
                    detailed_result = await self._run_chat_with_tool_loop(messages)
                    return detailed_result["final_text"]

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

        detailed_result = await self._run_chat_with_tool_loop(messages)
        return detailed_result["final_text"]

    async def chat_async_detailed(
        self,
        current_context: List[Dict[str, str]],
        retrieved_summaries: List[str],
        retrieved_conversations: List[str],
        recent_summaries: Optional[List[str]] = None,
        intermediate_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        """Async chat returning both final text and intermediate assistant messages."""
        messages = self._build_chat_messages(
            current_context,
            retrieved_summaries,
            retrieved_conversations,
            recent_summaries,
        )

        return await self._run_chat_with_tool_loop(
            messages, intermediate_callback=intermediate_callback
        )

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

        detailed_result = await self._run_chat_with_tool_loop(messages)
        return detailed_result["final_text"]

    async def chat_with_custom_message_async_detailed(
        self,
        current_context: List[Dict[str, str]],
        retrieved_summaries: List[str],
        retrieved_conversations: List[str],
        recent_summaries: Optional[List[str]] = None,
        custom_user_message: Optional[str] = None,
        intermediate_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        """Async chat with custom message, returning detailed assistant outputs."""
        messages = self._build_chat_messages(
            current_context,
            retrieved_summaries,
            retrieved_conversations,
            recent_summaries,
            custom_user_message=custom_user_message,
        )

        return await self._run_chat_with_tool_loop(
            messages, intermediate_callback=intermediate_callback
        )

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
                "content": f"{custom_user_message}",
            }
            messages.append(emphasized_message)
        elif current_context:
            current_user_message = current_context[-1]
            # Add emphasis to highlight this is the current request
            emphasized_message = {
                "role": current_user_message["role"],
                "content": f"Please respond to the current user request based on all context provided.\n\n⚡ [Current Request]\n{current_user_message['content']}",
            }
            messages.append(emphasized_message)

        return messages

    def generate_summary(
        self, existing_summary: Optional[str], new_conversations: List[Dict[str, str]]
    ) -> str:
        conv_text = self._format_conversation_messages(new_conversations)

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
        conv_text = self._format_conversation_messages(new_conversations)

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
        conv_text = self._format_conversation_messages(messages)

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
        conv_text = self._format_conversation_messages(messages)

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
        conv_text = self._format_conversation_messages(messages)

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
        conv_text = self._format_conversation_messages(messages)

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
