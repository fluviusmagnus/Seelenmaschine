import pytest
from unittest.mock import Mock, patch

from core.memory import MemoryManager
from core.database import DatabaseManager
from core.retriever import RetrievedSummary, RetrievedConversation
from llm.embedding import EmbeddingClient
from llm.reranker import RerankerClient


@pytest.fixture
def mock_db():
    """Create mock DatabaseManager."""
    db = Mock(DatabaseManager)
    db.get_active_session.return_value = None
    db.create_session.return_value = 1
    return db


@pytest.fixture
def mock_embedding_client():
    """Create mock EmbeddingClient."""
    client = Mock(EmbeddingClient)
    client.get_embedding.return_value = [0.1] * 1536
    return client


@pytest.fixture
def mock_reranker_client():
    """Create mock RerankerClient."""
    client = Mock(RerankerClient)
    client.is_enabled.return_value = False
    return client


@pytest.fixture
def memory_manager(mock_db, mock_embedding_client, mock_reranker_client):
    """Create MemoryManager with mock dependencies."""
    return MemoryManager(
        db=mock_db,
        embedding_client=mock_embedding_client,
        reranker_client=mock_reranker_client,
    )


class TestMemoryManager:
    """Test MemoryManager functionality."""

    def test_initialization(self, memory_manager):
        """Test memory manager initializes correctly."""
        assert memory_manager.db is not None
        assert memory_manager.embedding_client is not None
        assert memory_manager.reranker_client is not None
        assert memory_manager.context_window is not None
        assert memory_manager.retriever is not None

    def test_ensure_active_session_creates_session(self, memory_manager, mock_db):
        """Test that ensure_active_session creates a session if none exists."""
        mock_db.get_active_session.return_value = None
        memory_manager._ensure_active_session()
        assert mock_db.create_session.called

    def test_get_current_session_id(self, memory_manager, mock_db):
        """Test getting current session ID."""
        mock_db.get_active_session.return_value = {"session_id": 5}
        session_id = memory_manager.get_current_session_id()
        assert session_id == 5

    def test_get_current_session_id_no_session(self, memory_manager, mock_db):
        """Test getting session ID raises error when no active session."""
        mock_db.get_active_session.return_value = None
        with pytest.raises(RuntimeError):
            memory_manager.get_current_session_id()

    def test_new_session(self, memory_manager, mock_db):
        """Test creating a new session."""
        mock_db.get_active_session.return_value = {"session_id": 1}
        new_id = memory_manager.new_session()
        assert mock_db.close_session.called
        assert mock_db.create_session.called
        assert new_id == 1

    def test_new_session_with_remaining_messages(self, memory_manager, mock_db):
        """Test creating new session summarizes remaining messages."""
        mock_db.get_active_session.return_value = {"session_id": 1}
        mock_db.insert_summary.return_value = 10

        # Add some messages to context window
        memory_manager.context_window.add_message("user", "Hello")
        memory_manager.context_window.add_message("assistant", "Hi there")
        memory_manager.context_window.add_message("user", "How are you?")

        with patch.object(
            memory_manager, "_generate_summary", return_value="Final summary"
        ) as mock_summary:
            with patch.object(
                memory_manager, "_update_long_term_memory", return_value=True
            ) as mock_update_ltm:
                new_id = memory_manager.new_session()

                # Verify summary was created for remaining messages
                assert mock_summary.called
                assert mock_db.insert_summary.called

                # Verify long-term memory was updated with the remaining messages
                assert mock_update_ltm.called
                update_call_args = mock_update_ltm.call_args[0]
                assert update_call_args[0] == 10  # summary_id
                assert len(update_call_args[1]) == 3  # 3 remaining messages

                # Verify session was closed and new one created
                assert mock_db.close_session.called
                assert mock_db.create_session.called
                assert new_id == 1

    def test_new_session_no_existing(self, memory_manager, mock_db):
        """Test creating new session when none exists."""
        mock_db.get_active_session.return_value = None
        memory_manager.new_session()
        assert not mock_db.close_session.called
        assert mock_db.create_session.called

    def test_reset_session(self, memory_manager, mock_db):
        """Test resetting current session."""
        mock_db.get_active_session.return_value = {"session_id": 1}
        memory_manager.reset_session()
        assert mock_db.delete_session.called
        assert mock_db.create_session.called

    def test_add_user_message(self, memory_manager, mock_db):
        """Test adding user message."""
        mock_db.get_active_session.return_value = {"session_id": 1}
        mock_db.insert_conversation.return_value = 10

        conv_id, embedding = memory_manager.add_user_message("Hello")

        assert conv_id == 10
        assert len(embedding) == 1536
        assert mock_db.insert_conversation.called
        assert memory_manager.context_window.get_total_message_count() == 1

    def test_add_assistant_message(self, memory_manager, mock_db, monkeypatch):
        """Test adding assistant message."""
        # Mock Config values using monkeypatch
        from config import Config

        monkeypatch.setattr(Config, "CONTEXT_WINDOW_TRIGGER_SUMMARY", 100)

        mock_db.get_active_session.return_value = {"session_id": 1}
        mock_db.insert_conversation.return_value = 11

        conv_id, summary_id = memory_manager.add_assistant_message("Response")

        assert conv_id == 11
        assert mock_db.insert_conversation.called

    def test_add_assistant_message_triggers_summary(
        self, memory_manager, mock_db, monkeypatch
    ):
        """Test that adding assistant message triggers summary when threshold reached."""
        # Mock Config values
        from config import Config

        monkeypatch.setattr(Config, "CONTEXT_WINDOW_TRIGGER_SUMMARY", 24)
        monkeypatch.setattr(Config, "CONTEXT_WINDOW_KEEP_MIN", 12)

        mock_db.get_active_session.return_value = {"session_id": 1}
        mock_db.insert_conversation.return_value = 11
        mock_db.insert_summary.return_value = 1

        # Mock get_conversations_by_session to return conversations with proper timestamps
        mock_conversations = [
            {
                "conversation_id": i,
                "timestamp": 1000 + i * 100,
                "role": "user" if i % 2 == 0 else "assistant",
                "text": f"Message {i}",
            }
            for i in range(24)
        ]
        mock_db.get_conversations_by_session.return_value = mock_conversations

        # Add exactly 24 messages to trigger summary
        for i in range(24):
            memory_manager.context_window.add_message(
                "user" if i % 2 == 0 else "assistant", f"Message {i}"
            )

        # Mock both summary generation and memory update
        with patch.object(
            memory_manager, "_generate_summary", return_value="Test summary"
        ) as mock_summary:
            with patch.object(
                memory_manager,
                "_generate_memory_update",
                return_value='{"user": {"name": "Test"}}',
            ) as mock_memory_update:
                with patch.object(
                    memory_manager, "update_long_term_memory", return_value=True
                ) as mock_update_ltm:
                    conv_id, summary_id = memory_manager.add_assistant_message(
                        "Response"
                    )

                    assert summary_id is not None
                    assert mock_db.insert_summary.called

                    # Verify that _generate_memory_update was called with the correct messages
                    # It should be called with the 12 messages that were summarized (the earliest ones)
                    assert mock_memory_update.called
                    called_messages = mock_memory_update.call_args[0][0]

                    # The first 12 messages should have been used for the summary and memory update
                    assert len(called_messages) == 12
                    assert called_messages[0].text == "Message 0"
                    assert called_messages[11].text == "Message 11"

    def test_process_user_input(self, memory_manager):
        """Test processing user input retrieves related memories."""
        summaries = [
            RetrievedSummary(
                summary_id=1,
                summary="Summary 1",
                first_timestamp=100,
                last_timestamp=200,
                score=0.5,
            )
        ]
        conversations = [
            RetrievedConversation(
                conversation_id=1, timestamp=150, role="user", text="Test", score=0.5
            )
        ]

        with patch.object(
            memory_manager.retriever,
            "retrieve_related_memories",
            return_value=(summaries, conversations),
        ):
            with patch.object(
                memory_manager.retriever,
                "format_summaries_for_prompt",
                return_value=["Formatted Summary 1"],
            ):
                with patch.object(
                    memory_manager.retriever,
                    "format_conversations_for_prompt",
                    return_value=["Formatted Conv 1"],
                ):
                    formatted_summaries, formatted_convs = (
                        memory_manager.process_user_input("Hello")
                    )

                    assert len(formatted_summaries) == 1
                    assert len(formatted_convs) == 1

    def test_get_context_messages(self, memory_manager):
        """Test getting context messages."""
        memory_manager.context_window.add_message("user", "Hello")
        memory_manager.context_window.add_message("assistant", "Hi")

        context = memory_manager.get_context_messages()
        assert len(context) == 2
        assert context[0]["role"] == "user"
        assert context[0]["content"] == "Hello"  # Changed from "text" to "content"

    def test_get_recent_summaries(self, memory_manager, monkeypatch):
        """Test getting recent summaries."""
        from config import Config

        monkeypatch.setattr(Config, "RECENT_SUMMARIES_MAX", 3)

        memory_manager.context_window.add_summary("Summary 1", summary_id=1)
        memory_manager.context_window.add_summary("Summary 2", summary_id=2)

        summaries = memory_manager.get_recent_summaries()
        assert len(summaries) == 2
        assert summaries[0] == "Summary 1"

    def test_update_long_term_memory_invalid_json(self, memory_manager):
        """Test update_long_term_memory returns False for invalid JSON."""
        result = memory_manager.update_long_term_memory(1, "not json")
        assert result is False
