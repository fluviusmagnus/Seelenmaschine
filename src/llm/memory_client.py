import asyncio
from typing import Any, Callable, Dict, List, Optional

from core.config import Config
from utils.async_utils import ensure_not_in_async_context, run_sync
from utils.logger import get_logger

logger = get_logger()


class MemoryClient:
    """Handle summary and long-term memory generation prompts."""

    def __init__(self, llm_client: Any):
        self.llm_client = llm_client

    async def _run_tool_model_prompt(
        self,
        *,
        prompt: str,
        system_content: str,
        debug_prompt_label: str,
        debug_result_label: str,
    ) -> str:
        """Execute a prompt against the tool model and return the text result."""
        self.llm_client._ensure_tool_client_initialized()

        if Config.DEBUG_SHOW_FULL_PROMPT:
            logger.debug(
                f"{debug_prompt_label} ({self.llm_client.tool_model}):\n{prompt}"
            )

        outbound_messages = self.llm_client._normalize_outbound_messages(
            [
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt},
            ]
        )

        response = await self.llm_client._tool_client.chat.completions.create(
            model=self.llm_client.tool_model,
            messages=outbound_messages,
        )

        result = response.choices[0].message.content or ""
        if Config.DEBUG_SHOW_FULL_PROMPT:
            logger.debug(f"{debug_result_label}:\n{result}")
        return result

    def _run_sync_tool_prompt(self, coroutine_factory: Callable[[], Any]) -> str:
        """Run an async tool-model coroutine from sync code."""
        return run_sync(coroutine_factory, self.llm_client._get_event_loop)

    @staticmethod
    def _ensure_not_in_async_context(error_message: str) -> None:
        """Raise a clear error if a sync wrapper is called from async code."""
        ensure_not_in_async_context(error_message)

    def _build_conversation_prompt(
        self,
        messages: List[Dict[str, str]],
        prompt_builder: Callable[..., str],
        *prompt_args: Any,
    ) -> str:
        """Format messages and build the final prompt body."""
        conv_text = self.llm_client._format_conversation_messages(messages)
        return prompt_builder(conv_text, *prompt_args)

    def _run_sync_prompt_request(
        self,
        *,
        prompt: str,
        system_content: str,
        debug_prompt_label: str,
        debug_result_label: str,
        async_context_error: str,
    ) -> str:
        """Execute a tool-model prompt through the sync wrapper."""
        self._ensure_not_in_async_context(async_context_error)

        async def _request() -> str:
            return await self._run_tool_model_prompt(
                prompt=prompt,
                system_content=system_content,
                debug_prompt_label=debug_prompt_label,
                debug_result_label=debug_result_label,
            )

        return self._run_sync_tool_prompt(_request)

    def generate_summary(
        self,
        existing_summary: Optional[str],
        new_conversations: List[Dict[str, str]],
        prompt_builder: Callable[[Optional[str], str], str],
    ) -> str:
        """Generate a summary from conversation messages."""
        conv_text = self.llm_client._format_conversation_messages(new_conversations)
        prompt = prompt_builder(existing_summary, conv_text)
        return self._run_sync_prompt_request(
            prompt=prompt,
            system_content="You are a conversation summarizer.",
            debug_prompt_label="Summary prompt sent to tool_model",
            debug_result_label="Summary result from tool_model",
            async_context_error=(
                "generate_summary() called from async context. "
                "Use await generate_summary_async() instead."
            ),
        )

    async def generate_summary_async(
        self,
        existing_summary: Optional[str],
        new_conversations: List[Dict[str, str]],
        prompt_builder: Callable[[Optional[str], str], str],
    ) -> str:
        """Async version of generate_summary."""
        conv_text = self.llm_client._format_conversation_messages(new_conversations)
        prompt = prompt_builder(existing_summary, conv_text)

        return await self._run_tool_model_prompt(
            prompt=prompt,
            system_content="You are a conversation summarizer.",
            debug_prompt_label="Summary (async) prompt sent to tool_model",
            debug_result_label="Summary (async) result from tool_model",
        )

    def generate_memory_update(
        self,
        messages: List[Dict[str, str]],
        current_seele_json: str,
        prompt_builder: Callable[[str, str, Optional[int], Optional[int]], str],
        first_timestamp: Optional[int] = None,
        last_timestamp: Optional[int] = None,
    ) -> str:
        """Synchronous wrapper for memory update generation."""
        prompt = self._build_conversation_prompt(
            messages,
            prompt_builder,
            current_seele_json,
            first_timestamp,
            last_timestamp,
        )
        return self._run_sync_prompt_request(
            prompt=prompt,
            system_content="You generate JSON patches for memory updates.",
            debug_prompt_label="Memory update prompt sent to tool_model",
            debug_result_label="Memory update result from tool_model",
            async_context_error=(
                "generate_memory_update() called from async context. "
                "Use await generate_memory_update_async() instead."
            ),
        )

    async def generate_memory_update_async(
        self,
        messages: List[Dict[str, str]],
        current_seele_json: str,
        prompt_builder: Callable[[str, str, Optional[int], Optional[int]], str],
        first_timestamp: Optional[int] = None,
        last_timestamp: Optional[int] = None,
    ) -> str:
        """Async version of generate_memory_update."""
        prompt = self._build_conversation_prompt(
            messages,
            prompt_builder,
            current_seele_json,
            first_timestamp,
            last_timestamp,
        )

        return await self._run_tool_model_prompt(
            prompt=prompt,
            system_content="You generate JSON patches for memory updates.",
            debug_prompt_label="Memory update (async) prompt sent to tool_model",
            debug_result_label="Memory update (async) result from tool_model",
        )

    def generate_complete_memory_json(
        self,
        messages: List[Dict[str, str]],
        current_seele_json: str,
        error_message: str,
        previous_attempt: Optional[str],
        prompt_builder: Callable[
            [str, str, str, Optional[str], Optional[int], Optional[int]], str
        ],
        first_timestamp: Optional[int] = None,
        last_timestamp: Optional[int] = None,
    ) -> str:
        """Synchronous wrapper for full-memory regeneration."""
        prompt = self._build_conversation_prompt(
            messages,
            prompt_builder,
            current_seele_json,
            error_message,
            previous_attempt,
            first_timestamp,
            last_timestamp,
        )
        return self._run_sync_prompt_request(
            prompt=prompt,
            system_content="You generate complete seele.json objects for memory updates.",
            debug_prompt_label="Complete memory JSON prompt sent to tool_model",
            debug_result_label="Complete memory JSON result from tool_model",
            async_context_error=(
                "generate_complete_memory_json() called from async context. "
                "Use await generate_complete_memory_json_async() instead."
            ),
        )

    async def generate_complete_memory_json_async(
        self,
        messages: List[Dict[str, str]],
        current_seele_json: str,
        error_message: str,
        previous_attempt: Optional[str],
        prompt_builder: Callable[
            [str, str, str, Optional[str], Optional[int], Optional[int]], str
        ],
        first_timestamp: Optional[int] = None,
        last_timestamp: Optional[int] = None,
    ) -> str:
        """Async version of generate_complete_memory_json."""
        prompt = self._build_conversation_prompt(
            messages,
            prompt_builder,
            current_seele_json,
            error_message,
            previous_attempt,
            first_timestamp,
            last_timestamp,
        )

        return await self._run_tool_model_prompt(
            prompt=prompt,
            system_content=(
                "You generate complete seele.json objects for memory updates."
            ),
            debug_prompt_label=(
                "Complete memory JSON (async) prompt sent to tool_model"
            ),
            debug_result_label="Complete memory JSON (async) result from tool_model",
        )

    def generate_seele_repair(
        self,
        current_content: str,
        schema_template: str,
        error_message: str,
        repair_context: str,
        prompt_builder: Callable[[str, str, str, str, Optional[str]], str],
        previous_attempt: Optional[str] = None,
    ) -> str:
        """Synchronous wrapper for persisted seele.json repair/migration."""
        prompt = prompt_builder(
            current_content,
            schema_template,
            error_message,
            repair_context,
            previous_attempt,
        )
        return self._run_sync_prompt_request(
            prompt=prompt,
            system_content="You repair and migrate complete seele.json objects.",
            debug_prompt_label="Seele repair prompt sent to tool_model",
            debug_result_label="Seele repair result from tool_model",
            async_context_error=(
                "generate_seele_repair() called from async context. "
                "Use await generate_seele_repair_async() instead."
            ),
        )

    async def generate_seele_repair_async(
        self,
        current_content: str,
        schema_template: str,
        error_message: str,
        repair_context: str,
        prompt_builder: Callable[[str, str, str, str, Optional[str]], str],
        previous_attempt: Optional[str] = None,
    ) -> str:
        """Async version of persisted seele.json repair/migration."""
        prompt = prompt_builder(
            current_content,
            schema_template,
            error_message,
            repair_context,
            previous_attempt,
        )

        return await self._run_tool_model_prompt(
            prompt=prompt,
            system_content="You repair and migrate complete seele.json objects.",
            debug_prompt_label="Seele repair (async) prompt sent to tool_model",
            debug_result_label="Seele repair (async) result from tool_model",
        )

    def generate_seele_compaction(
        self,
        current_seele_json: str,
        personal_facts_limit: int,
        memorable_events_limit: int,
        prompt_builder: Callable[[str, int, int], str],
    ) -> str:
        """Synchronously compact overgrown seele memory sections."""
        prompt = prompt_builder(
            current_seele_json,
            personal_facts_limit,
            memorable_events_limit,
        )
        return self._run_sync_prompt_request(
            prompt=prompt,
            system_content="You compact overgrown seele.json memory sections.",
            debug_prompt_label="Seele compaction prompt sent to tool_model",
            debug_result_label="Seele compaction result from tool_model",
            async_context_error=(
                "generate_seele_compaction() called from async context. "
                "Use await generate_seele_compaction_async() instead."
            ),
        )

    async def generate_seele_compaction_async(
        self,
        current_seele_json: str,
        personal_facts_limit: int,
        memorable_events_limit: int,
        prompt_builder: Callable[[str, int, int], str],
    ) -> str:
        """Asynchronously compact overgrown seele memory sections."""
        prompt = prompt_builder(
            current_seele_json,
            personal_facts_limit,
            memorable_events_limit,
        )

        return await self._run_tool_model_prompt(
            prompt=prompt,
            system_content="You compact overgrown seele.json memory sections.",
            debug_prompt_label="Seele compaction (async) prompt sent to tool_model",
            debug_result_label="Seele compaction (async) result from tool_model",
        )

