import re
from typing import List, Dict, Any, Optional, Callable, Awaitable

from openai import AsyncOpenAI

from core.config import Config
from llm.memory_client import MemoryClient
from llm.request_executor import ChatRequestExecutor
from llm.tool_loop import ToolLoop
from prompts.chat_prompt import ChatMessageBuilder
from prompts.runtime import (
    get_complete_memory_json_prompt,
    get_cacheable_system_prompt,
    get_current_time_str,
    get_memory_update_prompt,
    get_seele_compaction_prompt,
    get_seele_repair_prompt,
    get_summary_prompt,
    load_seele_json,
)
from utils.logger import get_logger

logger = get_logger()


class LLMClient:
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

    def _normalize_outbound_messages(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Normalize outbound chat messages before sending them to a provider.

        For compatibility with some OpenAI-compatible providers, the final
        message should not use the ``system`` role. If the last message is a
        system message, rewrite only that message role to ``user`` while keeping
        the content unchanged.
        """
        normalized_messages = [dict(message) for message in messages]
        if not normalized_messages:
            return normalized_messages

        last_message = normalized_messages[-1]
        if last_message.get("role") == "system":
            normalized_messages[-1] = {
                **last_message,
                "role": "user",
            }
            logger.warning(
                "Normalized final outbound LLM message role from system to user "
                "for provider compatibility"
            )

        return normalized_messages

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

        if len(text) <= Config.TOOL_LLM_MAX_RESPONSE_CHARS:
            return text

        omitted_chars = len(text) - Config.TOOL_LLM_MAX_RESPONSE_CHARS
        head = text[: Config.TOOL_LLM_TRUNCATE_HEAD_CHARS].rstrip()
        tail = text[-Config.TOOL_LLM_TRUNCATE_TAIL_CHARS :].lstrip()
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

    async def _run_chat_messages(
        self,
        *,
        current_context: List[Dict[str, str]],
        retrieved_summaries: List[str],
        retrieved_conversations: List[str],
        recent_summaries: Optional[List[str]] = None,
        custom_user_message: Optional[str] = None,
        custom_message_role: str = "user",
        current_session_id: Optional[int] = None,
        intermediate_callback: Optional[Callable[[str], Awaitable[None]]] = None,
        abort_check: Optional[Callable[[], None]] = None,
    ) -> Dict[str, Any]:
        """Build prompt messages and execute the tool-aware chat loop."""
        messages = self._build_chat_messages(
            current_context,
            retrieved_summaries,
            retrieved_conversations,
            recent_summaries,
            current_session_id=current_session_id,
            custom_user_message=custom_user_message,
            custom_message_role=custom_message_role,
        )
        return await self._run_chat_with_tool_loop(
            messages,
            intermediate_callback=intermediate_callback,
            abort_check=abort_check,
        )

    async def _run_chat_messages_final_text(self, **kwargs: Any) -> str:
        """Execute a chat flow and return only the final assistant text."""
        detailed_result = await self._run_chat_messages(**kwargs)
        return detailed_result["final_text"]

    async def _run_chat_with_tool_loop(
        self,
        messages: List[Dict[str, str]],
        intermediate_callback: Optional[Callable[[str], Awaitable[None]]] = None,
        abort_check: Optional[Callable[[], None]] = None,
    ) -> Dict[str, Any]:
        """Run chat completion loop with tool execution and collect assistant texts."""
        return await self._tool_loop.run_chat_with_tool_loop(
            messages,
            intermediate_callback=intermediate_callback,
            abort_check=abort_check,
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

    async def chat_async(
        self,
        current_context: List[Dict[str, str]],
        retrieved_summaries: List[str],
        retrieved_conversations: List[str],
        recent_summaries: Optional[List[str]] = None,
        current_session_id: Optional[int] = None,
    ) -> str:
        """Async version of chat. Use this in async contexts.

        Always uses chat_model for conversation, even when tools are available.
        """
        return await self._run_chat_messages_final_text(
            current_context=current_context,
            retrieved_summaries=retrieved_summaries,
            retrieved_conversations=retrieved_conversations,
            recent_summaries=recent_summaries,
            current_session_id=current_session_id,
        )

    async def chat_async_detailed(
        self,
        current_context: List[Dict[str, str]],
        retrieved_summaries: List[str],
        retrieved_conversations: List[str],
        recent_summaries: Optional[List[str]] = None,
        current_session_id: Optional[int] = None,
        intermediate_callback: Optional[Callable[[str], Awaitable[None]]] = None,
        abort_check: Optional[Callable[[], None]] = None,
    ) -> Dict[str, Any]:
        """Async chat returning both final text and intermediate assistant messages."""
        return await self._run_chat_messages(
            current_context=current_context,
            retrieved_summaries=retrieved_summaries,
            retrieved_conversations=retrieved_conversations,
            recent_summaries=recent_summaries,
            current_session_id=current_session_id,
            intermediate_callback=intermediate_callback,
            abort_check=abort_check,
        )

    async def chat_with_custom_message_async(
        self,
        current_context: List[Dict[str, str]],
        retrieved_summaries: List[str],
        retrieved_conversations: List[str],
        recent_summaries: Optional[List[str]] = None,
        custom_user_message: Optional[str] = None,
        custom_message_role: str = "user",
        current_session_id: Optional[int] = None,
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
        return await self._run_chat_messages_final_text(
            current_context=current_context,
            retrieved_summaries=retrieved_summaries,
            retrieved_conversations=retrieved_conversations,
            recent_summaries=recent_summaries,
            custom_user_message=custom_user_message,
            custom_message_role=custom_message_role,
            current_session_id=current_session_id,
        )

    async def chat_with_custom_message_async_detailed(
        self,
        current_context: List[Dict[str, str]],
        retrieved_summaries: List[str],
        retrieved_conversations: List[str],
        recent_summaries: Optional[List[str]] = None,
        custom_user_message: Optional[str] = None,
        custom_message_role: str = "user",
        current_session_id: Optional[int] = None,
        intermediate_callback: Optional[Callable[[str], Awaitable[None]]] = None,
        abort_check: Optional[Callable[[], None]] = None,
    ) -> Dict[str, Any]:
        """Async chat with custom message, returning detailed assistant outputs."""
        return await self._run_chat_messages(
            current_context=current_context,
            retrieved_summaries=retrieved_summaries,
            retrieved_conversations=retrieved_conversations,
            recent_summaries=recent_summaries,
            custom_user_message=custom_user_message,
            custom_message_role=custom_message_role,
            current_session_id=current_session_id,
            abort_check=abort_check,
            intermediate_callback=intermediate_callback,
        )

    def _build_chat_messages(
        self,
        current_context: List[Dict[str, str]],
        retrieved_summaries: List[str],
        retrieved_conversations: List[str],
        recent_summaries: Optional[List[str]] = None,
        current_session_id: Optional[int] = None,
        custom_user_message: Optional[str] = None,
        custom_message_role: str = "user",
    ) -> List[Dict[str, str]]:
        """Build messages while preserving the native chat message structure.

        The cacheable system prompt remains the first system message. Retrieved
        memories and runtime context are added as separate system messages with
        XML-wrapped top-level sections, while the final user input remains a real
        user-role message.

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
            current_session_id=current_session_id,
            custom_user_message=custom_user_message,
            custom_message_role=custom_message_role,
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

    async def generate_complete_memory_json_async(
        self,
        messages: List[Dict[str, str]],
        current_seele_json: str,
        error_message: str,
        previous_attempt: Optional[str] = None,
        first_timestamp: Optional[int] = None,
        last_timestamp: Optional[int] = None,
    ) -> str:
        """Async version of generate_complete_memory_json. Use this in async contexts."""
        return await self._memory_client.generate_complete_memory_json_async(
            messages=messages,
            current_seele_json=current_seele_json,
            error_message=error_message,
            previous_attempt=previous_attempt,
            prompt_builder=get_complete_memory_json_prompt,
            first_timestamp=first_timestamp,
            last_timestamp=last_timestamp,
        )

    async def generate_seele_repair_async(
        self,
        current_content: str,
        schema_template: str,
        error_message: str,
        repair_context: str,
        previous_attempt: Optional[str] = None,
    ) -> str:
        """Repair or migrate a persisted seele.json document."""
        return await self._memory_client.generate_seele_repair_async(
            current_content=current_content,
            schema_template=schema_template,
            error_message=error_message,
            repair_context=repair_context,
            previous_attempt=previous_attempt,
            prompt_builder=get_seele_repair_prompt,
        )

    async def generate_seele_compaction_async(
        self,
        current_seele_json: str,
        personal_facts_limit: int,
        memorable_events_limit: int,
    ) -> str:
        """Asynchronously compact overgrown seele memory sections."""
        return await self._memory_client.generate_seele_compaction_async(
            current_seele_json=current_seele_json,
            personal_facts_limit=personal_facts_limit,
            memorable_events_limit=memorable_events_limit,
            prompt_builder=get_seele_compaction_prompt,
        )

    async def _async_close(self) -> None:
        if self._chat_client is not None:
            await self._chat_client.close()
            self._chat_client = None
        if self._tool_client is not None:
            await self._tool_client.close()
            self._tool_client = None

    async def close_async(self) -> None:
        """Async version of close. Use this in async contexts."""
        await self._async_close()
