import pytest
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from core.retriever import MemoryRetriever, RetrievedSummary, RetrievedConversation
from core.database import DatabaseManager
from llm.embedding import EmbeddingClient
from llm.reranker import RerankerClient


@pytest.fixture
def mock_db():
    """Create mock DatabaseManager."""
    return Mock(DatabaseManager)


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
def retriever(mock_db, mock_embedding_client, mock_reranker_client):
    """Create MemoryRetriever with mock dependencies."""
    return MemoryRetriever(
        db=mock_db,
        embedding_client=mock_embedding_client,
        reranker_client=mock_reranker_client
    )


class TestMemoryRetriever:
    """Test MemoryRetriever functionality."""

    def test_initialization(self, retriever, mock_db, mock_embedding_client, mock_reranker_client):
        """Test retriever initializes correctly."""
        assert retriever.db == mock_db
        assert retriever.embedding_client == mock_embedding_client
        assert retriever.reranker_client == mock_reranker_client

    def test_retrieve_retrieve_memories_without_reranker(self, retriever, mock_db, mock_embedding_client, monkeypatch):
        """Test retrieving memories without reranker."""
        # Mock Config values
        from config import Config
        monkeypatch.setattr(Config, 'RECALL_SUMMARY_PER_QUERY', 3)
        monkeypatch.setattr(Config, 'RECALL_CONV_PER_SUMMARY', 4)
        monkeypatch.setattr(Config, 'RERANK_TOP_SUMMARIES', 3)
        monkeypatch.setattr(Config, 'RERANK_TOP_CONVS', 6)
        
        mock_db.search_summaries.return_value = [
            (1, "Summary 1", 100, 200, 0.5)
        ]
        mock_db.search_conversations.return_value = [
            (1, 150, "user", "Test message", 0.5)
        ]

        summaries, conversations = retriever.retrieve_related_memories("test query", None)

        assert len(summaries) == 1
        assert len(conversations) == 1
        assert summaries[0].summary == "Summary 1"
        assert conversations[0].text == "Test message"

    def test_retrieve_memories_with_bot_message(self, retriever, mock_db, mock_embedding_client, monkeypatch):
        """Test retrieving memories with bot message."""
        # Mock Config values
        from config import Config
        monkeypatch.setattr(Config, 'RECALL_SUMMARY_PER_QUERY', 3)
        monkeypatch.setattr(Config, 'RECALL_CONV_PER_SUMMARY', 4)
        monkeypatch.setattr(Config, 'RERANK_TOP_SUMMARIES', 3)
        monkeypatch.setattr(Config, 'RERANK_TOP_CONVS', 6)
        
        mock_db.search_summaries.return_value = [
            (1, "Summary 1", 100, 200, 0.5)
        ]
        mock_db.search_conversations.return_value = []

        summaries, conversations = retriever.retrieve_related_memories("test query", "bot response")

        assert mock_db.search_summaries.call_count == 2

    def test_format_summaries_for_prompt(self, retriever, monkeypatch):
        """Test formatting summaries for prompt."""
        # Mock Config values with ZoneInfo object
        from config import Config
        monkeypatch.setattr(Config, 'TIMEZONE', ZoneInfo('UTC'))
        
        summaries = [
            RetrievedSummary(summary_id=1, summary="Test summary", first_timestamp=100, last_timestamp=200, score=0.5)
        ]

        formatted = retriever.format_summaries_for_prompt(summaries)
        assert len(formatted) == 1
        assert "Test summary" in formatted[0]

    def test_format_conversations_for_prompt(self, retriever, monkeypatch):
        """Test formatting conversations for prompt."""
        # Mock Config values with ZoneInfo object
        from config import Config
        monkeypatch.setattr(Config, 'TIMEZONE', ZoneInfo('UTC'))
        
        conversations = [
            RetrievedConversation(conversation_id=1, timestamp=150, role="user", text="Test message", score=0.5)
        ]

        formatted = retriever.format_conversations_for_prompt(conversations)
        assert len(formatted) == 1
        assert "User: Test message" in formatted[0]
