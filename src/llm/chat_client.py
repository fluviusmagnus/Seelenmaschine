import asyncio
import re
from typing import List, Dict, Any, Optional, Callable, Awaitable

from openai import AsyncOpenAI

from core.config import Config
from llm.memory_client import MemoryClient
from llm.message_builder import ChatMessageBuilder
from llm.request_executor import ChatRequestExecutor
from llm.tool_loop import ToolLoop
from prompts import (
    get_complete_memory_json_prompt,
    get_cacheable_system_prompt,
    get_current_time_str,
    get_memory_update_prompt,
    get_summary_prompt,
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
        self._memory_client = MemoryClient(self)
        self._message_builder = ChatMessageBuilder(self)
        self._chat_request = ChatRequestExecutor(self)
        self._tool_loop = ToolLoop(self)

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

    def _get_cacheable_system_prompt(
        self, recent_summaries: Optional[List[str]] = None
    ) -> str:
        """Build the cacheable system prompt."""
        return get_cacheable_system_prompt(recent_summaries)

    def _get_current_time_str(self) -> str:
        """Format the current time string for prompts."""
        return get_current_time_str()

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
        return await self._tool_loop.run_chat_with_tool_loop(
            messages,
            intermediate_callback=intermediate_callback,
        )

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
        return await self._chat_request.async_chat(
            messages=messages,
            use_tools=use_tools,
            force_chat_model=force_chat_model,
        )

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
        return self._message_builder.build_chat_messages(
            current_context=current_context,
            retrieved_summaries=retrieved_summaries,
            retrieved_conversations=retrieved_conversations,
            recent_summaries=recent_summaries,
            custom_user_message=custom_user_message,
        )

    def generate_summary(
        self, existing_summary: Optional[str], new_conversations: List[Dict[str, str]]
    ) -> str:
        return self._memory_client.generate_summary(
            existing_summary=existing_summary,
            new_conversations=new_conversations,
            prompt_builder=get_summary_prompt,
        )

    async def generate_summary_async(
        self, existing_summary: Optional[str], new_conversations: List[Dict[str, str]]
    ) -> str:
        """Async version of generate_summary. Use this in async contexts."""
        return await self._memory_client.generate_summary_async(
            existing_summary=existing_summary,
            new_conversations=new_conversations,
            prompt_builder=get_summary_prompt,
        )

    def generate_memory_update(
        self,
        messages: List[Dict[str, str]],
        current_seele_json: str,
        first_timestamp: Optional[int] = None,
        last_timestamp: Optional[int] = None,
    ) -> str:
        """Synchronous wrapper for generate_memory_update. Use generate_memory_update_async in async contexts."""
        return self._memory_client.generate_memory_update(
            messages=messages,
            current_seele_json=current_seele_json,
            prompt_builder=get_memory_update_prompt,
            first_timestamp=first_timestamp,
            last_timestamp=last_timestamp,
        )

    async def generate_memory_update_async(
        self,
        messages: List[Dict[str, str]],
        current_seele_json: str,
        first_timestamp: Optional[int] = None,
        last_timestamp: Optional[int] = None,
    ) -> str:
        """Async version of generate_memory_update. Use this in async contexts."""
        return await self._memory_client.generate_memory_update_async(
            messages=messages,
            current_seele_json=current_seele_json,
            prompt_builder=get_memory_update_prompt,
            first_timestamp=first_timestamp,
            last_timestamp=last_timestamp,
        )

    def generate_complete_memory_json(
        self,
        messages: List[Dict[str, str]],
        current_seele_json: str,
        error_message: str,
        first_timestamp: Optional[int] = None,
        last_timestamp: Optional[int] = None,
    ) -> str:
        """Synchronous wrapper for generating complete seele.json. Use generate_complete_memory_json_async in async contexts."""
        return self._memory_client.generate_complete_memory_json(
            messages=messages,
            current_seele_json=current_seele_json,
            error_message=error_message,
            prompt_builder=get_complete_memory_json_prompt,
            first_timestamp=first_timestamp,
            last_timestamp=last_timestamp,
        )

    async def generate_complete_memory_json_async(
        self,
        messages: List[Dict[str, str]],
        current_seele_json: str,
        error_message: str,
        first_timestamp: Optional[int] = None,
        last_timestamp: Optional[int] = None,
    ) -> str:
        """Async version of generate_complete_memory_json. Use this in async contexts."""
        return await self._memory_client.generate_complete_memory_json_async(
            messages=messages,
            current_seele_json=current_seele_json,
            error_message=error_message,
            prompt_builder=get_complete_memory_json_prompt,
            first_timestamp=first_timestamp,
            last_timestamp=last_timestamp,
        )

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

