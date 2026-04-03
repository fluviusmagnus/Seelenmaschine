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

    def _wrap_scheduled_task_message(
        self,
        task_message: str,
        task_name: str,
        task_id: Optional[str] = None,
    ) -> str:
        """Build the synthetic system message used for scheduled tasks."""
        trigger_time = get_current_timestamp()
        trigger_time_str = timestamp_to_str(trigger_time)
        return (
            f"[Scheduled Task]\n"
            f"This is a trigger message. Now execute the task described below and then continue the current conversation.\n\n"
            f"task_id: {task_id or 'unknown'}\n"
            f"name: {task_name}\n"
            f"trigger_time: {trigger_time_str}\n"
            f"message: {task_message}"
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
        await self.memory.add_scheduled_task_message_async(wrapped_message)

    async def _persist_system_event_message(self, message: str) -> None:
        """Persist a system event as a context-only system message."""
        await self.memory.add_system_event_message_async(message)

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
            await self.memory.add_tool_message_async(tool_message)

    async def _persist_conversation_events(
        self, conversation_events: List[Dict[str, str]], *, context_label: str
    ) -> None:
        """Persist assistant/tool events in the exact order they occurred."""
        if not conversation_events:
            return

        logger.debug(f"Persisting ordered conversation events ({context_label})")
        for event in conversation_events:
            role = event.get("role")
            content = event.get("content", "")
            if not content:
                continue

            if role == "assistant":
                _, summary_id = await self.memory.add_assistant_message_async(content)
                if summary_id:
                    logger.info(
                        f"Created new summary (ID: {summary_id}) during {context_label}"
                    )
            elif role == "system":
                await self.memory.add_tool_message_async(content)

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
            retrieved_summaries, retrieved_conversations, recent_summaries = (
                await self._retrieve_memory_context(
                    query_text=user_message,
                    current_context=current_context,
                    embedding=user_embedding,
                )
            )
            llm_result = await self._run_with_memory_search_tool(
                lambda: self.llm_client.chat_async_detailed(
                    current_context=current_context,
                    retrieved_summaries=retrieved_summaries,
                    retrieved_conversations=retrieved_conversations,
                    recent_summaries=recent_summaries,
                    current_session_id=self.memory.get_current_session_id(),
                    intermediate_callback=intermediate_callback,
                ),
                enable_log="Step 5: Enabling memory search tool",
                disable_log="Step 7: Disabling memory search tool",
                mcp_log="Step 5.5: Ensuring MCP is connected",
            )

            assistant_messages = llm_result.get("assistant_messages", [])
            tool_context_messages = llm_result.get("tool_context_messages", [])
            conversation_events = llm_result.get("conversation_events", [])
            response = llm_result.get("final_text", "")

            if self.config.DEBUG_SHOW_FULL_PROMPT:
                logger.debug(
                    "LLM detailed result for current message: "
                    f"assistant_messages={len(assistant_messages)}"
                )
            else:
                logger.debug(
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
            if conversation_events:
                await self._persist_conversation_events(
                    conversation_events,
                    context_label="message processing",
                )
            else:
                await self._persist_tool_context_messages(
                    tool_context_messages,
                    context_label="message processing",
                )
                await self._persist_assistant_messages(
                    assistant_messages,
                    context_label="message processing",
                )

            if not self.config.DEBUG_SHOW_FULL_PROMPT:
                logger.debug(
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
        task_id: Optional[str] = None,
        *,
        intermediate_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> str:
        """Process a scheduled task message through the LLM and memory."""
        try:
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
            retrieved_summaries, retrieved_conversations, recent_summaries = (
                await self._retrieve_memory_context(
                    query_text=task_message,
                    current_context=current_context,
                    embedding=task_embedding,
                    log_suffix=" for scheduled task",
                )
            )
            llm_result = await self._run_with_memory_search_tool(
                lambda: self.llm_client.chat_with_custom_message_async_detailed(
                    current_context=current_context,
                    retrieved_summaries=retrieved_summaries,
                    retrieved_conversations=retrieved_conversations,
                    recent_summaries=recent_summaries,
                    custom_user_message=wrapped_message,
                    custom_message_role="system",
                    current_session_id=self.memory.get_current_session_id(),
                    intermediate_callback=intermediate_callback,
                ),
                enable_log="Step 4: Enabling memory search tool",
                disable_log="Step 7: Disabling memory search tool",
                mcp_log="Step 4.5: Ensuring MCP is connected",
            )

            assistant_messages = llm_result.get("assistant_messages", [])
            tool_context_messages = llm_result.get("tool_context_messages", [])
            conversation_events = llm_result.get("conversation_events", [])
            response_text = llm_result.get("final_text", "")

            if self.config.DEBUG_SHOW_FULL_PROMPT:
                logger.debug(
                    "LLM detailed result for scheduled task: "
                    f"assistant_messages={len(assistant_messages)}"
                )
            else:
                logger.debug(
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

            logger.debug(
                "Step 8: Adding assistant responses to memory (scheduled task)"
            )
            if conversation_events:
                await self._persist_conversation_events(
                    conversation_events,
                    context_label="scheduled task processing",
                )
            else:
                await self._persist_tool_context_messages(
                    tool_context_messages,
                    context_label="scheduled task processing",
                )
                await self._persist_assistant_messages(
                    assistant_messages,
                    context_label="scheduled task processing",
                )

            if not self.config.DEBUG_SHOW_FULL_PROMPT:
                logger.debug(
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

    async def process_system_event(
        self,
        event_message: str,
        *,
        intermediate_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> str:
        """Process a system event message through the LLM and memory."""
        try:
            logger.debug(f"Wrapped system event message: {event_message[:100]}...")
            logger.debug("Step 1: Persisting system event message")
            await self._persist_system_event_message(event_message)

            logger.debug("Step 2: Getting current context for system event")
            current_context = self.memory.get_context_messages()

            logger.debug("Step 3: Retrieving relevant memories for system event")
            event_embedding = await self.embedding_client.get_embedding_async(
                event_message
            )
            retrieved_summaries, retrieved_conversations, recent_summaries = (
                await self._retrieve_memory_context(
                    query_text=event_message,
                    current_context=current_context,
                    embedding=event_embedding,
                    log_suffix=" for system event",
                )
            )
            llm_result = await self._run_with_memory_search_tool(
                lambda: self.llm_client.chat_with_custom_message_async_detailed(
                    current_context=current_context,
                    retrieved_summaries=retrieved_summaries,
                    retrieved_conversations=retrieved_conversations,
                    recent_summaries=recent_summaries,
                    custom_user_message=event_message,
                    custom_message_role="system",
                    current_session_id=self.memory.get_current_session_id(),
                    intermediate_callback=intermediate_callback,
                ),
                enable_log="Step 4: Enabling memory search tool",
                disable_log="Step 7: Disabling memory search tool",
                mcp_log="Step 4.5: Ensuring MCP is connected",
            )

            assistant_messages = llm_result.get("assistant_messages", [])
            tool_context_messages = llm_result.get("tool_context_messages", [])
            conversation_events = llm_result.get("conversation_events", [])
            response_text = llm_result.get("final_text", "")

            if self.config.DEBUG_SHOW_FULL_PROMPT:
                logger.debug(
                    "LLM detailed result for system event: "
                    f"assistant_messages={len(assistant_messages)}"
                )
            else:
                logger.debug(
                    "LLM detailed result for system event: "
                    f"assistant_messages={len(assistant_messages)}, "
                    f"final_text={self.preview_text(llm_result.get('final_text', ''))}"
                )
                for idx, assistant_message in enumerate(assistant_messages, start=1):
                    logger.debug(
                        "System event assistant message "
                        f"{idx}/{len(assistant_messages)} to persist: "
                        f"{self.preview_text(assistant_message)}"
                    )

            logger.debug("Step 8: Adding assistant responses to memory (system event)")
            if conversation_events:
                await self._persist_conversation_events(
                    conversation_events,
                    context_label="system event processing",
                )
            else:
                await self._persist_tool_context_messages(
                    tool_context_messages,
                    context_label="system event processing",
                )
                await self._persist_assistant_messages(
                    assistant_messages,
                    context_label="system event processing",
                )

            if not self.config.DEBUG_SHOW_FULL_PROMPT:
                logger.debug(
                    "System event processing complete, returning combined response: "
                    f"{self.preview_text(response_text)}"
                )
            return response_text
        except Exception as e:
            logger.error(f"Error in process_system_event: {e}", exc_info=True)
            return (
                f"[System Event] {event_message}\n\n"
                "(Error occurred while processing, please check logs)"
            )
