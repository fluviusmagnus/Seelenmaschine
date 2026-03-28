"""Conversation orchestration service."""

from typing import Any, Awaitable, Callable, Dict, List, Optional

from utils.logger import get_logger
from utils.time import get_current_timestamp, timestamp_to_str

logger = get_logger()


class ConversationService:
    """Coordinate memory retrieval, LLM calls, and response persistence."""

    def __init__(
        self,
        *,
        config: Any,
        memory: Any,
        embedding_client: Any,
        llm_client: Any,
        memory_search_tool: Any,
        mcp_client: Any,
        ensure_mcp_connected: Optional[Callable[[], Awaitable[None]]] = None,
        preview_text: Optional[Callable[[Optional[str], int], str]] = None,
    ) -> None:
        self.config = config
        self.memory = memory
        self.embedding_client = embedding_client
        self.llm_client = llm_client
        self.memory_search_tool = memory_search_tool
        self.mcp_client = mcp_client
        self.ensure_mcp_connected = ensure_mcp_connected
        self.preview_text = preview_text or self._default_preview_text

    @staticmethod
    def _default_preview_text(text: Optional[str], max_length: int = 120) -> str:
        """Build a compact single-line preview for logs."""
        if text is None:
            return ""

        normalized = " ".join(str(text).split())
        if len(normalized) <= max_length:
            return normalized
        return f"{normalized[:max_length]}..."

    @staticmethod
    def _find_last_bot_message(current_context: List[Dict[str, str]]) -> Optional[str]:
        """Extract the latest assistant message from context."""
        for msg in reversed(current_context):
            if msg.get("role") == "assistant":
                return msg.get("content", "")
        return None

    async def process_message(
        self,
        user_message: str,
        *,
        intermediate_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> str:
        """Process a normal user message through memory and the LLM."""
        try:
            logger.debug("Step 1: Adding user message to memory")
            _, user_embedding = await self.memory.add_user_message_async(user_message)

            logger.debug("Step 2: Getting current context")
            current_context = self.memory.get_context_messages()

            logger.debug("Step 3: Retrieving relevant memories")
            last_bot_message = self._find_last_bot_message(current_context)

            (
                retrieved_summaries,
                retrieved_conversations,
            ) = await self.memory.process_user_input_async(
                user_input=user_message,
                last_bot_message=last_bot_message,
                user_input_embedding=user_embedding,
            )

            logger.debug(
                f"Retrieved {len(retrieved_summaries)} summaries and "
                f"{len(retrieved_conversations)} conversations"
            )

            logger.debug("Step 4: Getting recent summaries")
            recent_summaries = self.memory.get_recent_summaries()
            logger.debug(f"Got {len(recent_summaries)} recent summaries")

            logger.debug("Step 5: Enabling memory search tool")
            self.memory_search_tool.enable()

            try:
                if self.mcp_client and self.ensure_mcp_connected is not None:
                    logger.debug("Step 5.5: Ensuring MCP is connected")
                    await self.ensure_mcp_connected()

                logger.debug("Step 6: Calling LLM")
                llm_result = await self.llm_client.chat_async_detailed(
                    current_context=current_context,
                    retrieved_summaries=retrieved_summaries,
                    retrieved_conversations=retrieved_conversations,
                    recent_summaries=recent_summaries,
                    intermediate_callback=intermediate_callback,
                )
            finally:
                logger.debug("Step 7: Disabling memory search tool")
                self.memory_search_tool.disable()

            assistant_messages = llm_result.get("assistant_messages", [])
            response = llm_result.get("final_text", "")

            logger.info(
                "LLM detailed result for current message: "
                f"assistant_messages={len(assistant_messages)}, "
                f"final_text={self.preview_text(llm_result.get('final_text', ''))}"
            )
            for idx, assistant_message in enumerate(assistant_messages, start=1):
                logger.debug(
                    f"Assistant message {idx}/{len(assistant_messages)} to persist: "
                    f"{self.preview_text(assistant_message)}"
                )

            logger.debug("Step 8: Adding assistant responses to memory")
            for assistant_message in assistant_messages:
                _, summary_id = await self.memory.add_assistant_message_async(
                    assistant_message
                )
                if summary_id:
                    logger.info(
                        "Created new summary "
                        f"(ID: {summary_id}) during message processing"
                    )

            logger.info(
                "Message processing complete, returning combined response: "
                f"{self.preview_text(response)}"
            )
            return response
        except Exception as e:
            logger.error(f"Error in process_message: {e}", exc_info=True)
            raise

    async def process_scheduled_task(
        self,
        task_message: str,
        task_name: str = "Scheduled Task",
        *,
        intermediate_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> str:
        """Process a scheduled task message through the LLM and memory."""
        try:
            trigger_time = get_current_timestamp()
            trigger_time_str = timestamp_to_str(trigger_time)
            wrapped_message = (
                f"[SYSTEM_SCHEDULED_TASK]\n"
                f"Task Name: {task_name}\n"
                f"Trigger Time: {trigger_time_str}\n"
                f"Task: {task_message}\n\n"
                f"Please respond proactively based on this scheduled task."
            )

            logger.debug(f"Wrapped scheduled task message: {wrapped_message[:100]}...")
            logger.debug("Step 1: Getting current context for scheduled task")
            current_context = self.memory.get_context_messages()

            logger.debug("Step 2: Retrieving relevant memories for scheduled task")
            task_embedding = await self.embedding_client.get_embedding_async(task_message)
            last_bot_message = self._find_last_bot_message(current_context)

            (
                retrieved_summaries,
                retrieved_conversations,
            ) = await self.memory.process_user_input_async(
                user_input=task_message,
                last_bot_message=last_bot_message,
                user_input_embedding=task_embedding,
            )

            logger.debug(
                f"Retrieved {len(retrieved_summaries)} summaries and "
                f"{len(retrieved_conversations)} conversations for scheduled task"
            )

            logger.debug("Step 3: Getting recent summaries")
            recent_summaries = self.memory.get_recent_summaries()
            logger.debug(f"Got {len(recent_summaries)} recent summaries")

            logger.debug("Step 4: Enabling memory search tool")
            if self.memory_search_tool:
                self.memory_search_tool.enable()

            try:
                if self.mcp_client and self.ensure_mcp_connected is not None:
                    logger.debug("Step 4.5: Ensuring MCP is connected")
                    await self.ensure_mcp_connected()

                logger.debug("Step 5-6: Calling LLM with custom task message")
                llm_result = (
                    await self.llm_client.chat_with_custom_message_async_detailed(
                        current_context=current_context,
                        retrieved_summaries=retrieved_summaries,
                        retrieved_conversations=retrieved_conversations,
                        recent_summaries=recent_summaries,
                        custom_user_message=wrapped_message,
                        intermediate_callback=intermediate_callback,
                    )
                )
            finally:
                logger.debug("Step 7: Disabling memory search tool")
                if self.memory_search_tool:
                    self.memory_search_tool.disable()

            assistant_messages = llm_result.get("assistant_messages", [])
            response_text = llm_result.get("final_text", "")

            logger.info(
                "LLM detailed result for scheduled task: "
                f"assistant_messages={len(assistant_messages)}, "
                f"final_text={self.preview_text(llm_result.get('final_text', ''))}"
            )
            for idx, assistant_message in enumerate(assistant_messages, start=1):
                logger.debug(
                    "Scheduled task assistant message "
                    f"{idx}/{len(assistant_messages)} to persist: "
                    f"{self.preview_text(assistant_message)}"
                )

            logger.debug("Step 8: Adding assistant responses to memory (scheduled task)")
            for assistant_message in assistant_messages:
                _, summary_id = await self.memory.add_assistant_message_async(
                    assistant_message
                )
                if summary_id:
                    logger.info(
                        "Created new summary "
                        f"(ID: {summary_id}) during scheduled task processing"
                    )

            logger.info(
                "Scheduled task processing complete, returning combined response: "
                f"{self.preview_text(response_text)}"
            )
            return response_text
        except Exception as e:
            logger.error(f"Error in process_scheduled_task: {e}", exc_info=True)
            return (
                f"[Scheduled Task] {task_message}\n\n"
                "(Error occurred while processing, please check logs)"
            )
