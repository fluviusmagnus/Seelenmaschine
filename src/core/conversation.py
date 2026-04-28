"""Conversation orchestration service."""

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional

from texts import EventTexts
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
        begin_run: Optional[Callable[[], None]] = None,
        end_run: Optional[Callable[[], None]] = None,
        check_stop_requested: Optional[Callable[[], None]] = None,
    ) -> None:
        self.config = config
        self.memory = memory
        self.embedding_client = embedding_client
        self.llm_client = llm_client
        self.memory_search_tool = memory_search_tool
        self.mcp_client = mcp_client
        self.ensure_mcp_connected = ensure_mcp_connected
        self.preview_text = preview_text or self._default_preview_text
        self.begin_run = begin_run or (lambda: None)
        self.end_run = end_run or (lambda: None)
        self.check_stop_requested = check_stop_requested or (lambda: None)
        self._processing_lock = asyncio.Lock()

    @property
    def processing_lock(self) -> asyncio.Lock:
        """Expose the conversation processing lock for adapter-level sequencing."""
        return self._processing_lock

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

    def _wrap_scheduled_task_message(
        self,
        task_message: str,
        task_name: str,
        task_id: Optional[str] = None,
    ) -> str:
        """Build the synthetic system message used for scheduled tasks."""
        trigger_time = get_current_timestamp()
        trigger_time_str = timestamp_to_str(trigger_time)
        return EventTexts.scheduled_task_event(
            task_message=task_message,
            task_name=task_name,
            task_id=task_id,
            trigger_time=trigger_time_str,
        )

    async def _persist_scheduled_task_trigger_message(
        self, wrapped_message: str
    ) -> None:
        """Persist the scheduled-task trigger as a context-only system message.

        This mirrors tool-call context behavior: the message enters the current
        context window for future turns, but it is not counted as a normal
        user/assistant turn, is not summarized, and is not part of vector
        retrieval because it is stored as a non-conversation message type.
        """
        await self.memory.add_context_message_async(
            wrapped_message,
            role="system",
            message_type="scheduled_task",
            include_in_turn_count=False,
            include_in_summary=False,
            embedding=None,
        )

    async def _retrieve_memory_context(
        self,
        *,
        query_text: str,
        current_context: List[Dict[str, str]],
        embedding: List[float],
        log_suffix: str = "",
    ) -> tuple[List[str], List[str], List[str]]:
        """Collect retrieved memories and recent summaries for an input query."""
        last_bot_message = self._find_last_bot_message(current_context)
        retrieved_summaries, retrieved_conversations = (
            await self.memory.process_user_input_async(
                user_input=query_text,
                last_bot_message=last_bot_message,
                user_input_embedding=embedding,
            )
        )
        recent_summaries = self.memory.get_recent_summaries()

        logger.debug(
            f"Retrieved {len(retrieved_summaries)} summaries and "
            f"{len(retrieved_conversations)} conversations{log_suffix}"
        )
        logger.debug(f"Got {len(recent_summaries)} recent summaries")
        return retrieved_summaries, retrieved_conversations, recent_summaries

    async def _run_with_memory_search_tool(
        self,
        operation: Callable[[], Awaitable[Dict[str, Any]]],
        *,
        enable_log: str,
        disable_log: str,
        mcp_log: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run an LLM operation while memory-search tooling is temporarily enabled."""
        tool = self.memory_search_tool
        if tool:
            logger.debug(enable_log)
            tool.enable()

        try:
            if self.mcp_client and self.ensure_mcp_connected is not None:
                logger.debug(mcp_log or "Ensuring MCP is connected")
                await self.ensure_mcp_connected()
            return await operation()
        finally:
            if tool:
                logger.debug(disable_log)
                tool.disable()

    async def _persist_assistant_messages(
        self, assistant_messages: List[str], *, context_label: str
    ) -> None:
        """Persist assistant messages and log any summaries created during save."""
        logger.debug(f"Persisting assistant responses to memory ({context_label})")
        for assistant_message in assistant_messages:
            _, summary_id = await self.memory.add_assistant_message_async(
                assistant_message
            )
            if summary_id:
                logger.info(
                    f"Created new summary (ID: {summary_id}) during {context_label}"
                )

    async def _persist_tool_context_messages(
        self, tool_context_messages: List[str], *, context_label: str
    ) -> None:
        """Persist tool call context messages to the current session context."""
        if not tool_context_messages:
            return

        logger.debug(f"Persisting tool context messages ({context_label})")
        for tool_message in tool_context_messages:
            await self.memory.add_context_message_async(
                tool_message,
                role="system",
                message_type="tool_call",
                include_in_turn_count=False,
                include_in_summary=False,
                embedding=None,
            )

    async def _persist_conversation_events(
        self, conversation_events: List[Dict[str, Any]], *, context_label: str
    ) -> None:
        """Persist assistant/tool events in the exact order they occurred."""
        if not conversation_events:
            return

        logger.debug(f"Persisting ordered conversation events ({context_label})")
        for event in sorted(
            conversation_events,
            key=lambda item: int(item.get("event_index", 0)),
        ):
            role = event.get("role")
            content = event.get("content", "")
            message_type = event.get("message_type") or (
                "tool_call" if role == "system" else "conversation"
            )
            if not content:
                continue

            if role == "assistant" and message_type == "conversation":
                _, summary_id = await self.memory.add_assistant_message_async(content)
                if summary_id:
                    logger.info(
                        f"Created new summary (ID: {summary_id}) during {context_label}"
                    )
            elif role == "system" and message_type == "tool_call":
                await self.memory.add_context_message_async(
                    content,
                    role="system",
                    message_type="tool_call",
                    include_in_turn_count=False,
                    include_in_summary=False,
                    embedding=None,
                )

    async def _persist_llm_result(
        self,
        llm_result: Dict[str, Any],
        *,
        context_label: str,
        result_log_label: str,
    ) -> str:
        """Persist LLM output and return the final text."""
        assistant_messages = llm_result.get("assistant_messages", [])
        tool_context_messages = llm_result.get("tool_context_messages", [])
        conversation_events = llm_result.get("conversation_events", [])
        response_text = llm_result.get("final_text", "")

        if self.config.DEBUG_SHOW_FULL_PROMPT:
            logger.debug(
                f"LLM detailed result for {result_log_label}: "
                f"assistant_messages={len(assistant_messages)}"
            )
        else:
            logger.debug(
                f"LLM detailed result for {result_log_label}: "
                f"assistant_messages={len(assistant_messages)}, "
                f"final_text={self.preview_text(response_text)}"
            )
            for idx, assistant_message in enumerate(assistant_messages, start=1):
                logger.debug(
                    f"{result_log_label} assistant message "
                    f"{idx}/{len(assistant_messages)} to persist: "
                    f"{self.preview_text(assistant_message)}"
                )

        logger.debug(f"Persisting LLM result ({context_label})")
        if conversation_events:
            await self._persist_conversation_events(
                conversation_events,
                context_label=context_label,
            )
        else:
            await self._persist_tool_context_messages(
                tool_context_messages,
                context_label=context_label,
            )
            await self._persist_assistant_messages(
                assistant_messages,
                context_label=context_label,
            )

        if not self.config.DEBUG_SHOW_FULL_PROMPT:
            logger.debug(
                f"{result_log_label} complete, returning combined response: "
                f"{self.preview_text(response_text)}"
            )
        return response_text

    async def _execute_llm_turn(
        self,
        *,
        query_text: str,
        current_context: List[Dict[str, str]],
        embedding: List[float],
        operation: Callable[[List[str], List[str], List[str]], Awaitable[Dict[str, Any]]],
        retrieval_log_suffix: str,
        enable_log: str,
        disable_log: str,
        mcp_log: str,
        context_label: str,
        result_log_label: str,
    ) -> str:
        """Run the shared memory-retrieval + LLM + persistence turn flow."""
        retrieved_summaries, retrieved_conversations, recent_summaries = (
            await self._retrieve_memory_context(
                query_text=query_text,
                current_context=current_context,
                embedding=embedding,
                log_suffix=retrieval_log_suffix,
            )
        )
        self.check_stop_requested()
        llm_result = await self._run_with_memory_search_tool(
            lambda: operation(
                retrieved_summaries,
                retrieved_conversations,
                recent_summaries,
            ),
            enable_log=enable_log,
            disable_log=disable_log,
            mcp_log=mcp_log,
        )
        self.check_stop_requested()
        return await self._persist_llm_result(
            llm_result,
            context_label=context_label,
            result_log_label=result_log_label,
        )

    async def run_post_response_summary_check(self, *, context_label: str) -> Optional[int]:
        """Run an explicit summary check after a reply has been delivered."""
        summary_id = await self.memory.run_summary_check_async()
        if summary_id is not None:
            logger.info(
                f"Created new summary (ID: {summary_id}) after {context_label}"
            )
        else:
            logger.debug(f"No summary created after {context_label}")
        return summary_id

    async def process_message(
        self,
        user_message: str,
        *,
        message_for_embedding: Optional[str] = None,
        intermediate_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> str:
        """Process a normal user message through memory and the LLM."""
        self.begin_run()
        try:
            self.check_stop_requested()
            logger.debug("Step 1: Adding user message to memory")
            embedding = None
            if message_for_embedding is not None:
                embedding = await self.embedding_client.get_embedding_async(
                    message_for_embedding
                )

            _, user_embedding = await self.memory.add_user_message_async(
                user_message,
                embedding=embedding,
            )

            logger.debug("Step 2: Getting current context")
            current_context = self.memory.get_context_messages()

            logger.debug("Step 3: Retrieving relevant memories")
            response = await self._execute_llm_turn(
                query_text=user_message,
                current_context=current_context,
                embedding=user_embedding,
                operation=lambda retrieved_summaries, retrieved_conversations, recent_summaries: self.llm_client.chat_async_detailed(
                    current_context=current_context,
                    retrieved_summaries=retrieved_summaries,
                    retrieved_conversations=retrieved_conversations,
                    recent_summaries=recent_summaries,
                    current_session_id=self.memory.get_current_session_id(),
                    intermediate_callback=intermediate_callback,
                    abort_check=self.check_stop_requested,
                ),
                retrieval_log_suffix="",
                enable_log="Step 5: Enabling memory search tool",
                disable_log="Step 7: Disabling memory search tool",
                mcp_log="Step 5.5: Ensuring MCP is connected",
                context_label="message processing",
                result_log_label="current message",
            )
            return response
        except Exception as e:
            logger.error(f"Error in process_message: {e}", exc_info=True)
            raise
        finally:
            self.end_run()

    async def process_scheduled_task(
        self,
        task_message: str,
        task_name: str = EventTexts.DEFAULT_SCHEDULED_TASK_NAME,
        task_id: Optional[str] = None,
        *,
        intermediate_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> str:
        """Process a scheduled task message through the LLM and memory."""
        self.begin_run()
        try:
            self.check_stop_requested()
            wrapped_message = self._wrap_scheduled_task_message(
                task_message,
                task_name,
                task_id,
            )

            logger.debug(f"Wrapped scheduled task message: {wrapped_message[:100]}...")
            logger.debug("Step 1: Persisting scheduled task trigger message")
            await self._persist_scheduled_task_trigger_message(wrapped_message)

            logger.debug("Step 2: Getting current context for scheduled task")
            current_context = self.memory.get_context_messages()

            logger.debug("Step 3: Retrieving relevant memories for scheduled task")
            task_embedding = await self.embedding_client.get_embedding_async(
                task_message
            )
            response_text = await self._execute_llm_turn(
                query_text=task_message,
                current_context=current_context,
                embedding=task_embedding,
                operation=lambda retrieved_summaries, retrieved_conversations, recent_summaries: self.llm_client.chat_with_custom_message_async_detailed(
                    current_context=current_context,
                    retrieved_summaries=retrieved_summaries,
                    retrieved_conversations=retrieved_conversations,
                    recent_summaries=recent_summaries,
                    custom_user_message=wrapped_message,
                    custom_message_role="user",
                    current_session_id=self.memory.get_current_session_id(),
                    intermediate_callback=intermediate_callback,
                    abort_check=self.check_stop_requested,
                ),
                retrieval_log_suffix=" for scheduled task",
                enable_log="Step 4: Enabling memory search tool",
                disable_log="Step 7: Disabling memory search tool",
                mcp_log="Step 4.5: Ensuring MCP is connected",
                context_label="scheduled task processing",
                result_log_label="scheduled task",
            )
            return response_text
        except Exception as e:
            logger.error(f"Error in process_scheduled_task: {e}", exc_info=True)
            raise
        finally:
            self.end_run()
