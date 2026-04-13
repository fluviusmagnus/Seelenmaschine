from typing import Any, Dict, List, Optional, Tuple

from memory.context import ContextWindow, Message
from core.database import DatabaseManager
from memory.vector_retriever import VectorRetriever
from llm.embedding import EmbeddingClient
from llm.reranker import RerankerClient
from memory.recall import MemoryRecall
from memory.seele import Seele
from memory.sessions import SessionMemory
from memory.summaries import SummaryGenerator
from utils.logger import get_logger

logger = get_logger()


class MemoryManager:
    def __init__(
        self,
        db: DatabaseManager,
        embedding_client: EmbeddingClient,
        reranker_client: RerankerClient,
    ):
        self.db = db
        self.embedding_client = embedding_client
        self.reranker_client = reranker_client

        self.context_window = ContextWindow()
        self.retriever = VectorRetriever(db, embedding_client, reranker_client)
        self.seele = Seele(db)
        self.sessions = SessionMemory(
            db=db,
            embedding_client=embedding_client,
            context_window=self.context_window,
        )
        self.summary_generator = SummaryGenerator()
        self.recall = MemoryRecall(
            context_window=self.context_window,
            retriever=self.retriever,
        )

        self._ensure_active_session()

    def _ensure_active_session(self) -> None:
        """Ensure there's an active session, create one if not."""
        self.sessions.ensure_active_session(
            restore_context_from_session=self.sessions.restore_context_from_session
        )

    def get_current_session_id(self) -> int:
        """Get current active session ID."""
        active_session = self.db.get_active_session()
        if active_session:
            return active_session["session_id"]
        raise RuntimeError("No active session found")

    def new_session(self) -> int:
        """Create a new session and close the old one if exists.

        Before closing the old session, summarizes all remaining conversations
        in the context window and updates long-term memory.
        """
        return self.sessions.new_session(
            generate_summary=self._generate_summary,
            update_long_term_memory=self._update_long_term_memory,
        )

    async def new_session_async(self) -> int:
        """Async version of new_session. Use this in async contexts.

        Create a new session and close the old one if exists.
        Before closing the old session, summarizes all remaining conversations
        in the context window and updates long-term memory.
        """
        return await self.sessions.new_session_async(
            generate_summary_async=self._generate_summary_async,
            update_long_term_memory_async=self._update_long_term_memory_async,
        )

    def reset_session(self) -> None:
        """Delete current session and create a new one."""
        self.sessions.reset_session()

    def process_user_input(
        self, user_input: str, last_bot_message: Optional[str] = None
    ) -> Tuple[List[str], List[str]]:
        """Process user input and retrieve related memories.

        Excludes recent summaries already in context window from vector search.
        """
        return self.recall.process_user_input(
            user_input=user_input,
            last_bot_message=last_bot_message,
        )

    async def process_user_input_async(
        self,
        user_input: str,
        last_bot_message: Optional[str] = None,
        user_input_embedding: Optional[List[float]] = None,
    ) -> Tuple[List[str], List[str]]:
        """Async version of process_user_input.

        Excludes recent summaries already in context window from vector search.

        Args:
            user_input: User input text
            last_bot_message: Optional last bot message for dual-query
            user_input_embedding: Optional pre-computed embedding
        """
        return await self.recall.process_user_input_async(
            user_input=user_input,
            last_bot_message=last_bot_message,
            user_input_embedding=user_input_embedding,
        )

    def add_user_message(
        self, text: str, embedding: Optional[List[float]] = None
    ) -> Tuple[int, List[float]]:
        session_id = self.get_current_session_id()
        return self.sessions.add_user_message(
            session_id=session_id,
            text=text,
            embedding=embedding,
        )

    async def add_user_message_async(
        self, text: str, embedding: Optional[List[float]] = None
    ) -> Tuple[int, List[float]]:
        """Async version of add_user_message. Use this in async contexts.

        Returns:
            Tuple of (conversation_id, embedding) - embedding is returned for reuse
        """
        session_id = self.get_current_session_id()
        return await self.sessions.add_user_message_async(
            session_id=session_id,
            text=text,
            embedding=embedding,
        )

    def add_assistant_message(
        self, text: str, embedding: Optional[List[float]] = None
    ) -> Tuple[int, Optional[int]]:
        session_id = self.get_current_session_id()
        return self.sessions.add_assistant_message(
            session_id=session_id,
            text=text,
            embedding=embedding,
        )

    async def add_assistant_message_async(
        self, text: str, embedding: Optional[List[float]] = None
    ) -> Tuple[int, Optional[int]]:
        """Async version of add_assistant_message. Use this in async contexts."""
        session_id = self.get_current_session_id()
        return await self.sessions.add_assistant_message_async(
            session_id=session_id,
            text=text,
            embedding=embedding,
        )

    async def run_summary_check_async(self) -> Optional[int]:
        """Explicitly check whether the current context should be summarized."""
        summary_id, summarized_messages = await self._check_and_create_summary_async()
        if summary_id is not None and summarized_messages is not None:
            await self._update_long_term_memory_async(summary_id, summarized_messages)
        return summary_id

    def add_context_message(
        self,
        text: str,
        *,
        role: str,
        message_type: str,
        include_in_turn_count: bool,
        include_in_summary: bool,
        embedding: Optional[List[float]] = None,
    ) -> int:
        """Persist a generic context message in the current session."""
        session_id = self.get_current_session_id()
        return self.sessions.add_context_message(
            session_id=session_id,
            text=text,
            role=role,
            message_type=message_type,
            include_in_turn_count=include_in_turn_count,
            include_in_summary=include_in_summary,
            embedding=embedding,
        )

    async def add_context_message_async(
        self,
        text: str,
        *,
        role: str,
        message_type: str,
        include_in_turn_count: bool,
        include_in_summary: bool,
        embedding: Optional[List[float]] = None,
    ) -> int:
        """Async version of add_context_message."""
        session_id = self.get_current_session_id()
        return await self.sessions.add_context_message_async(
            session_id=session_id,
            text=text,
            role=role,
            message_type=message_type,
            include_in_turn_count=include_in_turn_count,
            include_in_summary=include_in_summary,
            embedding=embedding,
        )

    def _check_and_create_summary(
        self,
    ) -> Tuple[Optional[int], Optional[List[Message]]]:
        """Check if summary should be created and create it.

        Returns:
            Tuple of (summary_id, messages_used_for_summary)
        """
        return self.sessions.check_and_create_summary(
            get_current_session_id=self.get_current_session_id,
            generate_summary=self._generate_summary,
        )

    async def _check_and_create_summary_async(
        self,
    ) -> Tuple[Optional[int], Optional[List[Message]]]:
        """Async version of _check_and_create_summary.

        Returns:
            Tuple of (summary_id, messages_used_for_summary)
        """
        return await self.sessions.check_and_create_summary_async(
            get_current_session_id=self.get_current_session_id,
            generate_summary_async=self._generate_summary_async,
        )

    def _generate_summary(self, messages: List[Message]) -> str:
        """Generate an independent summary for the given messages.

        Each summary is independent and only covers the specific messages provided.
        Summaries are later retrieved via vector search based on relevance, not
        by sequential order.
        """
        return self.summary_generator.generate_summary(messages)

    async def _generate_summary_async(self, messages: List[Message]) -> str:
        """Async version of _generate_summary. Use this in async contexts."""
        return await self.summary_generator.generate_summary_async(messages)

    def _generate_memory_update(self, messages: List[Message], summary_id: int) -> str:
        """Generate a memory update JSON patch from summarized messages."""
        return self.seele.generate_memory_update(messages, summary_id)

    def _generate_complete_memory_json(
        self, messages: List[Message], error_message: str, summary_id: int
    ) -> str:
        """Generate a complete seele.json document when patching fails."""
        return self.seele.generate_complete_memory_json(
            messages,
            error_message,
            summary_id,
        )

    async def _generate_memory_update_async(
        self, messages: List[Message], summary_id: int
    ) -> str:
        """Async version of _generate_memory_update."""
        return await self.seele.generate_memory_update_async(messages, summary_id)

    async def _generate_complete_memory_json_async(
        self, messages: List[Message], error_message: str, summary_id: int
    ) -> str:
        """Async version of _generate_complete_memory_json."""
        return await self.seele.generate_complete_memory_json_async(
            messages,
            error_message,
            summary_id,
        )

    def _update_long_term_memory(
        self, summary_id: int, messages: List[Message]
    ) -> bool:
        """Update long-term memory using the messages that were just summarized.

        Args:
            summary_id: The ID of the summary that was just created
            messages: The messages that were used to generate the summary

        Returns:
            True if update was successful, False otherwise
        """
        try:
            if not messages:
                return False

            json_patch = self._generate_memory_update(messages, summary_id)
            if not json_patch:
                return False

            return self.update_long_term_memory(summary_id, json_patch, messages)
        except Exception as e:
            logger.error(f"Failed to update long-term memory: {e}")
            return False

    async def _update_long_term_memory_async(
        self, summary_id: int, messages: List[Message]
    ) -> bool:
        """Async version of _update_long_term_memory.

        Args:
            summary_id: The ID of the summary that was just created
            messages: The messages that were used to generate the summary

        Returns:
            True if update was successful, False otherwise
        """
        try:
            if not messages:
                return False

            json_patch = await self._generate_memory_update_async(messages, summary_id)
            if not json_patch:
                return False

            return await self.update_long_term_memory_async(
                summary_id, json_patch, messages
            )
        except Exception as e:
            logger.error(f"Failed to update long-term memory: {e}")
            return False

    def update_long_term_memory(
        self, summary_id: int, json_patch: str, messages: Optional[List[Message]] = None
    ) -> bool:
        """Update long-term memory (seele.json) with a JSON Patch.

        If JSON Patch fails, falls back to generating complete seele.json.

        Args:
            summary_id: ID of the summary triggering the update
            json_patch: JSON string - should be a JSON Patch array (RFC 6902)
                       Also accepts dict format for backward compatibility
            messages: Optional messages used for fallback if patch fails

        Returns:
            True if successful, False otherwise
        """
        return self.seele.update_long_term_memory(summary_id, json_patch, messages)

    def _clean_json_response(self, response: str) -> str:
        """Clean LLM response to extract valid JSON.

        Args:
            response: Raw response from LLM

        Returns:
            Cleaned JSON string
        """
        return self.seele.clean_json_response(response)

    def _validate_seele_structure(self, data: dict) -> bool:
        """Validate that the seele.json structure has all required fields.

        Args:
            data: Parsed JSON data

        Returns:
            True if valid, False otherwise
        """
        return self.seele.validate_seele_structure(data)

    async def update_long_term_memory_async(
        self, summary_id: int, json_patch: str, messages: Optional[List[Message]] = None
    ) -> bool:
        """Async version of update_long_term_memory. Use this in async contexts.

        If JSON Patch fails, falls back to generating complete seele.json.
        """
        return await self.seele.update_long_term_memory_async(
            summary_id, json_patch, messages
        )

    def get_long_term_memory(self) -> Dict[str, Any]:
        return self.seele.get_long_term_memory()

    def ensure_long_term_memory_schema(self) -> bool:
        """Ensure persisted long-term memory matches the latest schema."""
        return self.seele.ensure_seele_schema_current()

    def get_context_messages(self) -> List[Dict[str, str]]:
        return self.recall.get_context_messages()

    def get_recent_summaries(self) -> List[str]:
        return self.recall.get_recent_summaries()

