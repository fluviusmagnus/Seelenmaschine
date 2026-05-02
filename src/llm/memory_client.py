from typing import Any, Callable, Dict, List, Optional

from core.config import Config
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

    def _build_conversation_prompt(
        self,
        messages: List[Dict[str, str]],
        prompt_builder: Callable[..., str],
        *prompt_args: Any,
    ) -> str:
        """Format messages and build the final prompt body."""
        conv_text = self.llm_client._format_conversation_messages(messages)
        return prompt_builder(conv_text, *prompt_args)

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

    async def generate_seele_repair_async(
        self,
        current_content: str,
        schema_template: str,
        error_message: str,
        repair_context: str,
        prompt_builder: Callable[[str, str, str, str, Optional[str]], str],
        previous_attempt: Optional[str] = None,
    ) -> str:
        """Repair or migrate a persisted seele.json document."""
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
            debug_prompt_label="Seele repair prompt sent to tool_model",
            debug_result_label="Seele repair result from tool_model",
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

    async def generate_short_term_compaction_async(
        self,
        fields_json: str,
        bot_name: str,
        user_name: str,
        prompt_builder: Callable[[str, str, str], str],
    ) -> str:
        """Asynchronously compact overflowing short-term emotion/need lists."""
        prompt = prompt_builder(fields_json, bot_name, user_name)

        return await self._run_tool_model_prompt(
            prompt=prompt,
            system_content="You compact short-term emotions and needs into long-term memory summaries.",
            debug_prompt_label="Short-term compaction (async) prompt sent to tool_model",
            debug_result_label="Short-term compaction (async) result from tool_model",
        )
