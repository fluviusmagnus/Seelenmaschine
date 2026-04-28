from typing import Any, Dict, List, Optional, Tuple

from memory.context import ContextWindow, Message
from core.database import DatabaseManager
from memory.vector_retriever import VectorRetriever
from llm.embedding import EmbeddingClient
from llm.chat_client import LLMClient
from llm.reranker import RerankerClient
from memory.seele import Seele
from memory.sessions import SessionMemory
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

    async def new_session_async(self) -> int:
        """Async version of new_session. Use this in async contexts.

        Create a new session and close the old one if exists.
        Before closing the old session, summarizes all remaining conversations
        in the context window and updates long-term memory.
        """
        new_session_id = await self.sessions.new_session_async(
            generate_summary_async=self._generate_summary_async,
            update_long_term_memory_async=self._update_long_term_memory_async,
        )
        self.seele.capture_session_snapshot(new_session_id)
        return new_session_id

    def reset_session(self) -> None:
        """Delete current session and create a new one."""
        old_session = self.db.get_active_session()
        if old_session:
            self.seele.restore_session_snapshot(int(old_session["session_id"]))
        self.sessions.reset_session()
        self.seele.capture_session_snapshot(self.get_current_session_id())

    def ensure_session_snapshot_current(self) -> None:
        """Ensure the active session has a matching seele reset snapshot."""
        self.seele.ensure_session_snapshot_current(self.get_current_session_id())

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
        exclude_summary_ids = self.context_window.get_recent_summary_ids()
        messages = self.context_window.get_messages()
        last_bot_embedding = None

        for msg in reversed(messages):
            if msg.role == "assistant" and msg.embedding:
                last_bot_embedding = msg.embedding
                break

        if user_input_embedding is None and messages:
            last_msg = messages[-1]
            if last_msg.role == "user" and last_msg.text == user_input:
                user_input_embedding = last_msg.embedding

        summaries, conversations = await self.retriever.retrieve_related_memories_async(
            query=user_input,
            last_bot_message=last_bot_message,
            query_embedding=user_input_embedding,
            last_bot_embedding=last_bot_embedding,
            exclude_summary_ids=exclude_summary_ids,
        )
        return (
            self.retriever.format_summaries_for_prompt(summaries),
            self.retriever.format_conversations_for_prompt(conversations),
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

    async def _generate_summary_async(self, messages: List[Message]) -> str:
        """Async version of _generate_summary. Use this in async contexts."""
        client = LLMClient()
        messages_dict = [msg.to_dict() for msg in messages]
        try:
            return await client.generate_summary_async(None, messages_dict)
        finally:
            await client.close_async()

    async def _generate_memory_update_async(
        self, messages: List[Message], summary_id: int
    ) -> str:
        """Async version of _generate_memory_update."""
        return await self.seele.generate_memory_update_async(messages, summary_id)

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
        return self.context_window.get_context_as_messages()

    def get_recent_summaries(self) -> List[str]:
        return self.context_window.get_recent_summaries_as_text()
