"""Session lifecycle orchestration."""

from typing import Any

from utils.logger import get_logger

logger = get_logger()


class SessionService:
    """Coordinate session lifecycle operations across memory and tool state."""

    def __init__(
        self,
        *,
        memory: Any,
        tool_trace_store: Any,
        memory_search_tool: Any = None,
    ) -> None:
        self.memory = memory
        self.tool_trace_store = tool_trace_store
        self.memory_search_tool = memory_search_tool

    def _sync_memory_search_session(self, session_id: int) -> None:
        """Keep the memory search tool aligned with the active session."""
        if self.memory_search_tool is None:
            return
        self.memory_search_tool.session_id = int(session_id)
        logger.info(f"Updated memory_search_tool session_id to {session_id}")

    def _prune_tool_trace_history(self) -> None:
        """Trim tool trace history after explicit session lifecycle changes."""
        self.tool_trace_store.prune_to_max_records()

    async def create_new_session(self) -> int:
        """Archive the current session and start a new one."""
        logger.info("Creating new session")
        new_session_id = await self.memory.new_session_async()
        logger.info(f"Created new session {new_session_id}")
        self._sync_memory_search_session(new_session_id)
        self._prune_tool_trace_history()
        return int(new_session_id)

    def reset_session(self) -> int:
        """Delete the current session and return the fresh active session id."""
        logger.info("Resetting session")
        self.memory.reset_session()
        session_id = int(self.memory.get_current_session_id())
        self._sync_memory_search_session(session_id)
        self._prune_tool_trace_history()
        return session_id
