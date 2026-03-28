from typing import Awaitable, Callable, List, Optional, Tuple

from memory.context import ContextWindow, Message
from core.database import DatabaseManager
from llm.embedding import EmbeddingClient
from utils.logger import get_logger
from utils.text import strip_blockquotes
from utils.time import get_current_timestamp

logger = get_logger()


class SessionMemory:
    """Manage session lifecycle, message persistence, and summary creation."""

    def __init__(
        self,
        db: DatabaseManager,
        embedding_client: EmbeddingClient,
        context_window: ContextWindow,
    ):
        self.db = db
        self.embedding_client = embedding_client
        self.context_window = context_window

    def _estimate_summary_window(
        self, messages: List[Message]
    ) -> Tuple[int, int]:
        """Estimate a timestamp window for synthetic session-close summaries."""
        last_timestamp = get_current_timestamp()
        first_timestamp = int(last_timestamp - len(messages) * 60)
        return first_timestamp, last_timestamp

    def _insert_summary(
        self,
        session_id: int,
        summary_text: str,
        first_timestamp: int,
        last_timestamp: int,
        embedding: List[float],
    ) -> int:
        """Persist a summary record and return its ID."""
        return self.db.insert_summary(
            session_id=session_id,
            summary=summary_text,
            first_timestamp=first_timestamp,
            last_timestamp=last_timestamp,
            embedding=embedding,
        )

    def _close_old_session(self, session_id: int) -> None:
        """Close an active session using the current timestamp."""
        self.db.close_session(session_id, get_current_timestamp())
        logger.info(f"Closed session: {session_id}")

    def _create_fresh_session(self, log_message: str) -> int:
        """Create a new active session and clear the in-memory context."""
        new_session_id = self.db.create_session(get_current_timestamp())
        self.context_window.clear()
        logger.info(f"{log_message}: {new_session_id}")
        return new_session_id

    def _store_message(
        self,
        session_id: int,
        timestamp: int,
        role: str,
        text: str,
        embedding: List[float],
    ) -> int:
        """Persist a conversation message and mirror it into the context window."""
        conversation_id = self.db.insert_conversation(
            session_id=session_id,
            timestamp=timestamp,
            role=role,
            text=text,
            embedding=embedding,
        )
        self.context_window.add_message(role=role, text=text, embedding=embedding)
        return conversation_id

    @staticmethod
    def _assistant_text_for_storage(text: str) -> str:
        """Strip memory citations unless debug mode requires full storage."""
        from core.config import Config

        return text if Config.DEBUG_MODE else strip_blockquotes(text)

    def _summary_timestamps_from_conversations(
        self, session_id: int, message_count: int
    ) -> Tuple[int, int]:
        """Resolve summary timestamps from stored conversations when possible."""
        conversations = self.db.get_conversations_by_session(session_id)
        if conversations and len(conversations) >= message_count:
            return conversations[0]["timestamp"], conversations[message_count - 1][
                "timestamp"
            ]

        first_timestamp = get_current_timestamp()
        last_timestamp = get_current_timestamp()
        logger.warning("Could not get real timestamps from database, using current time")
        return first_timestamp, last_timestamp

    def ensure_active_session(
        self, restore_context_from_session: Callable[[int], None]
    ) -> None:
        """Ensure there's an active session, create one if not."""
        active_session = self.db.get_active_session()
        if active_session is None:
            session_id = self.db.create_session(get_current_timestamp())
            logger.info(f"Created new active session: {session_id}")
            return

        session_id = active_session["session_id"]
        restore_context_from_session(session_id)
        logger.info(f"Restored context from active session: {session_id}")

    def restore_context_from_session(self, session_id: int) -> None:
        """Restore the context window from summaries and unsummarized messages."""
        from core.config import Config

        max_recent_summaries = Config.RECENT_SUMMARIES_MAX
        existing_summaries = self.db.get_summaries_by_session(session_id)

        if existing_summaries:
            recent_summaries = existing_summaries[:max_recent_summaries]
            for summary_row in reversed(recent_summaries):
                self.context_window.add_summary(
                    summary=summary_row["summary"],
                    summary_id=summary_row["summary_id"],
                )
            logger.info(
                f"Restored {len(recent_summaries)} existing summaries to context window"
            )

        unsummarized_conversations = self.db.get_unsummarized_conversations(session_id)
        total_count = len(unsummarized_conversations)

        if total_count == 0:
            logger.info("No unsummarized conversations to restore")
            return

        for conv in unsummarized_conversations:
            self.context_window.add_message(role=conv["role"], text=conv["text"])

        logger.info(f"Restored {total_count} unsummarized messages to context window")

    def new_session(
        self,
        generate_summary: Callable[[List[Message]], str],
        update_long_term_memory: Callable[[int, List[Message]], bool],
    ) -> int:
        """Create a new session and close the old one if needed."""
        old_session = self.db.get_active_session()
        if old_session:
            remaining_messages = self.context_window.context_window
            if remaining_messages:
                logger.info(
                    f"Summarizing {len(remaining_messages)} remaining messages before closing session"
                )
                summary_text = generate_summary(remaining_messages)
                first_timestamp, last_timestamp = self._estimate_summary_window(
                    remaining_messages
                )
                embedding = self.embedding_client.get_embedding(summary_text)
                summary_id = self._insert_summary(
                    session_id=old_session["session_id"],
                    summary_text=summary_text,
                    first_timestamp=first_timestamp,
                    last_timestamp=last_timestamp,
                    embedding=embedding,
                )
                logger.info(
                    f"Created final summary for session {old_session['session_id']}: summary_id={summary_id}"
                )
                update_long_term_memory(summary_id, remaining_messages)

            self._close_old_session(old_session["session_id"])

        return self._create_fresh_session("Created new session")

    async def new_session_async(
        self,
        generate_summary_async: Callable[[List[Message]], Awaitable[str]],
        update_long_term_memory_async: Callable[
            [int, List[Message]], Awaitable[bool]
        ],
    ) -> int:
        """Async version of new_session."""
        old_session = self.db.get_active_session()
        if old_session:
            remaining_messages = self.context_window.context_window
            if remaining_messages:
                logger.info(
                    f"Summarizing {len(remaining_messages)} remaining messages before closing session"
                )
                summary_text = await generate_summary_async(remaining_messages)
                first_timestamp, last_timestamp = self._estimate_summary_window(
                    remaining_messages
                )
                embedding = await self.embedding_client.get_embedding_async(
                    summary_text
                )
                summary_id = self._insert_summary(
                    session_id=old_session["session_id"],
                    summary_text=summary_text,
                    first_timestamp=first_timestamp,
                    last_timestamp=last_timestamp,
                    embedding=embedding,
                )
                logger.info(
                    f"Created final summary for session {old_session['session_id']}: summary_id={summary_id}"
                )
                await update_long_term_memory_async(summary_id, remaining_messages)

            self._close_old_session(old_session["session_id"])

        return self._create_fresh_session("Created new session")

    def reset_session(self) -> None:
        """Delete the current session and create a new one."""
        old_session = self.db.get_active_session()
        if old_session:
            session_id = old_session["session_id"]
            self.db.delete_session(session_id)
            logger.info(f"Deleted session: {session_id}")

        self._create_fresh_session("Created new session after reset")

    def add_user_message(
        self, session_id: int, text: str, embedding: Optional[List[float]] = None
    ) -> Tuple[int, List[float]]:
        """Store a user message and append it to the context window."""
        timestamp = get_current_timestamp()

        if embedding is None:
            embedding = self.embedding_client.get_embedding(strip_blockquotes(text))

        conversation_id = self._store_message(
            session_id=session_id,
            timestamp=timestamp,
            role="user",
            text=text,
            embedding=embedding,
        )
        logger.debug(f"Added user message: conversation_id={conversation_id}")
        return conversation_id, embedding

    async def add_user_message_async(
        self, session_id: int, text: str, embedding: Optional[List[float]] = None
    ) -> Tuple[int, List[float]]:
        """Async version of add_user_message."""
        timestamp = get_current_timestamp()

        if embedding is None:
            embedding = await self.embedding_client.get_embedding_async(
                strip_blockquotes(text)
            )

        conversation_id = self._store_message(
            session_id=session_id,
            timestamp=timestamp,
            role="user",
            text=text,
            embedding=embedding,
        )
        logger.debug(f"Added user message: conversation_id={conversation_id}")
        return conversation_id, embedding

    def add_assistant_message(
        self,
        session_id: int,
        text: str,
        check_and_create_summary: Callable[
            [], Tuple[Optional[int], Optional[List[Message]]]
        ],
        update_long_term_memory: Callable[[int, List[Message]], bool],
        embedding: Optional[List[float]] = None,
    ) -> Tuple[int, Optional[int]]:
        """Store an assistant message and trigger summarization when needed."""
        timestamp = get_current_timestamp()
        text_for_storage = self._assistant_text_for_storage(text)

        if embedding is None:
            embedding = self.embedding_client.get_embedding(strip_blockquotes(text))

        conversation_id = self._store_message(
            session_id=session_id,
            timestamp=timestamp,
            role="assistant",
            text=text_for_storage,
            embedding=embedding,
        )

        summary_id, summarized_messages = check_and_create_summary()
        if summary_id is not None and summarized_messages is not None:
            update_long_term_memory(summary_id, summarized_messages)

        logger.debug(f"Added assistant message: conversation_id={conversation_id}")
        return conversation_id, summary_id

    async def add_assistant_message_async(
        self,
        session_id: int,
        text: str,
        check_and_create_summary_async: Callable[
            [], Awaitable[Tuple[Optional[int], Optional[List[Message]]]]
        ],
        update_long_term_memory_async: Callable[
            [int, List[Message]], Awaitable[bool]
        ],
        embedding: Optional[List[float]] = None,
    ) -> Tuple[int, Optional[int]]:
        """Async version of add_assistant_message."""
        timestamp = get_current_timestamp()
        text_for_storage = self._assistant_text_for_storage(text)

        if embedding is None:
            embedding = await self.embedding_client.get_embedding_async(
                strip_blockquotes(text)
            )

        conversation_id = self._store_message(
            session_id=session_id,
            timestamp=timestamp,
            role="assistant",
            text=text_for_storage,
            embedding=embedding,
        )

        summary_id, summarized_messages = await check_and_create_summary_async()
        if summary_id is not None and summarized_messages is not None:
            await update_long_term_memory_async(summary_id, summarized_messages)

        logger.debug(f"Added assistant message: conversation_id={conversation_id}")
        return conversation_id, summary_id

    def check_and_create_summary(
        self,
        get_current_session_id: Callable[[], int],
        generate_summary: Callable[[List[Message]], str],
    ) -> Tuple[Optional[int], Optional[List[Message]]]:
        """Create a summary when the context window exceeds the threshold."""
        from core.config import Config

        trigger_count = Config.CONTEXT_WINDOW_TRIGGER_SUMMARY
        keep_count = Config.CONTEXT_WINDOW_KEEP_MIN

        if self.context_window.get_total_message_count() < trigger_count:
            return None, None

        messages_to_summarize = self.context_window.get_messages_for_summary(keep_count)
        if not messages_to_summarize:
            return None, None

        summary_text = generate_summary(messages_to_summarize)
        session_id = get_current_session_id()
        message_count = len(messages_to_summarize)
        first_timestamp, last_timestamp = self._summary_timestamps_from_conversations(
            session_id, message_count
        )

        embedding = self.embedding_client.get_embedding(summary_text)
        summary_id = self._insert_summary(
            session_id=session_id,
            summary_text=summary_text,
            first_timestamp=first_timestamp,
            last_timestamp=last_timestamp,
            embedding=embedding,
        )
        self.context_window.add_summary(summary=summary_text, summary_id=summary_id)
        self.context_window.remove_earliest_messages(keep_count)

        logger.info(
            f"Created summary: summary_id={summary_id}, length={len(summary_text)}"
        )
        return summary_id, messages_to_summarize

    async def check_and_create_summary_async(
        self,
        get_current_session_id: Callable[[], int],
        generate_summary_async: Callable[[List[Message]], Awaitable[str]],
    ) -> Tuple[Optional[int], Optional[List[Message]]]:
        """Async version of check_and_create_summary."""
        from core.config import Config

        trigger_count = Config.CONTEXT_WINDOW_TRIGGER_SUMMARY
        keep_count = Config.CONTEXT_WINDOW_KEEP_MIN

        if self.context_window.get_total_message_count() < trigger_count:
            return None, None

        messages_to_summarize = self.context_window.get_messages_for_summary(keep_count)
        if not messages_to_summarize:
            return None, None

        summary_text = await generate_summary_async(messages_to_summarize)
        session_id = get_current_session_id()
        message_count = len(messages_to_summarize)
        first_timestamp, last_timestamp = self._summary_timestamps_from_conversations(
            session_id, message_count
        )

        embedding = await self.embedding_client.get_embedding_async(summary_text)
        summary_id = self._insert_summary(
            session_id=session_id,
            summary_text=summary_text,
            first_timestamp=first_timestamp,
            last_timestamp=last_timestamp,
            embedding=embedding,
        )
        self.context_window.add_summary(summary=summary_text, summary_id=summary_id)
        self.context_window.remove_earliest_messages(keep_count)

        logger.info(
            f"Created summary: summary_id={summary_id}, length={len(summary_text)}"
        )
        return summary_id, messages_to_summarize


