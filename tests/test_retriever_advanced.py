"""Advanced tests for Memory Retriever

This module contains comprehensive tests for:
- Vector similarity search with dual queries
- Reranking logic
- Result formatting
- Exclusion filters
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from typing import List, Dict, Any, Tuple


class TestMemoryRetrieverDualQuery:
    """Test dual-query retrieval with bot message"""
    
    @pytest.fixture
    def mock_db(self):
        """Create a mock DatabaseManager"""
        db = Mock()
        db.search_conversations.return_value = []
        db.search_summaries.return_value = []
        return db
    
    @pytest.fixture
    def mock_embedding_client(self):
        """Create a mock EmbeddingClient"""
        client = Mock()
        client.get_embedding.return_value = [0.1] * 1536
        return client
    
    @pytest.fixture
    def mock_reranker_client(self):
        """Create a mock RerankerClient"""
        client = Mock()
        client.rerank.return_value = []
        return client
    
    def test_retrieve_with_bot_message_dual_query(self, mock_db, mock_embedding_client, mock_reranker_client):
        """Test that both user query and bot message are embedded and searched"""
        from core.retriever import MemoryRetriever
        
        retriever = MemoryRetriever(
            db=mock_db,
            embedding_client=mock_embedding_client,
            reranker_client=mock_reranker_client
        )
        
        user_query = "What did we discuss yesterday?"
        bot_message = "We talked about your project plans."
        
        # Mock the database search to return empty results
        mock_db.search_summaries.return_value = []
        mock_db.search_conversations.return_value = []
        
        # Call retrieve
        summaries, conversations = retriever.retrieve_related_memories(
            query=user_query,
            last_bot_message=bot_message
        )
        
        # Verify that embedding was called twice (for user query and bot message)
        assert mock_embedding_client.get_embedding.call_count == 2
        
        # Verify the calls were made with correct arguments
        call_args_list = mock_embedding_client.get_embedding.call_args_list
        assert call_args_list[0][0][0] == user_query
        assert call_args_list[1][0][0] == bot_message
    
    def test_retrieve_without_bot_message_single_query(self, mock_db, mock_embedding_client, mock_reranker_client):
        """Test that only user query is embedded when no bot message"""
        from core.retriever import MemoryRetriever
        
        retriever = MemoryRetriever(
            db=mock_db,
            embedding_client=mock_embedding_client,
            reranker_client=mock_reranker_client
        )
        
        user_query = "What did we discuss yesterday?"
        
        # Mock the database search
        mock_db.search_summaries.return_value = []
        mock_db.search_conversations.return_value = []
        
        # Call retrieve without bot message
        summaries, conversations = retriever.retrieve_related_memories(
            query=user_query,
            last_bot_message=None
        )
        
        # Verify that embedding was called only once (just user query)
        assert mock_embedding_client.get_embedding.call_count == 1


class TestMemoryRetrieverReranking:
    """Test reranking logic"""
    
    @pytest.fixture
    def mock_db(self):
        db = Mock()
        return db
    
    @pytest.fixture
    def mock_embedding_client(self):
        client = Mock()
        client.get_embedding.return_value = [0.1] * 1536
        return client
    
    @pytest.fixture
    def mock_reranker_client(self):
        client = Mock()
        return client
    
    def test_reranking_applied_to_results(self, mock_db, mock_embedding_client, mock_reranker_client):
        """Test that reranking is applied to search results"""
        from core.retriever import MemoryRetriever
        
        retriever = MemoryRetriever(
            db=mock_db,
            embedding_client=mock_embedding_client,
            reranker_client=mock_reranker_client
        )
        
        # Mock search results
        mock_db.search_summaries.return_value = [
            (1, "Summary 1", 1000, 2000, 0.8),
            (2, "Summary 2", 1100, 2100, 0.7)
        ]
        mock_db.search_conversations.return_value = [
            (10, 1500, "user", "Hello", 0.9),
            (11, 1600, "assistant", "Hi there", 0.8)
        ]
        
        # Mock reranker to return results in different order
        # Note: reranker returns documents with their original fields plus score
        # For summaries: text, summary_id, first_timestamp, last_timestamp
        # For conversations: text, conversation_id, timestamp, role
        mock_reranker_client.rerank.return_value = [
            {"text": "Summary 2", "summary_id": 2, "first_timestamp": 1100, "last_timestamp": 2100, "score": 0.95},
            {"text": "Summary 1", "summary_id": 1, "first_timestamp": 1000, "last_timestamp": 2000, "score": 0.85}
        ]
        
        # Also mock the conversations rerank since both are called
        def mock_rerank_side_effect(query, documents, top_n):
            # Return documents in reverse order with high scores
            return [{**doc, "score": 0.9 - i*0.01} for i, doc in enumerate(reversed(documents))]
        
        mock_reranker_client.rerank.side_effect = mock_rerank_side_effect
        
        # Call retrieve
        summaries, conversations = retriever.retrieve_related_memories(
            query="test query"
        )
        
        # Verify reranking was called
        mock_reranker_client.rerank.assert_called()


class TestMemoryRetrieverExclusion:
    """Test exclusion filters"""
    
    @pytest.fixture
    def mock_db(self):
        db = Mock()
        db.search_conversations.return_value = []
        db.search_summaries.return_value = []
        return db
    
    @pytest.fixture
    def mock_embedding_client(self):
        client = Mock()
        client.get_embedding.return_value = [0.1] * 1536
        return client
    
    @pytest.fixture
    def mock_reranker_client(self):
        client = Mock()
        client.rerank.return_value = []
        return client
    
    def test_exclude_recent_summaries_from_search(self, mock_db, mock_embedding_client, mock_reranker_client):
        """Test that recent summary IDs are excluded from search"""
        from core.retriever import MemoryRetriever
        
        retriever = MemoryRetriever(
            db=mock_db,
            embedding_client=mock_embedding_client,
            reranker_client=mock_reranker_client
        )
        
        # Exclude summary IDs 1, 2, 3
        exclude_ids = [1, 2, 3]
        
        # Call retrieve with excluded IDs
        summaries, conversations = retriever.retrieve_related_memories(
            query="test query",
            exclude_summary_ids=exclude_ids
        )
        
        # Verify search was called with exclusion
        call_args = mock_db.search_summaries.call_args
        assert 'exclude_ids' in str(call_args)


class TestMemoryRetrieverFormatting:
    """Test result formatting"""
    
    def test_format_summaries_for_prompt(self):
        """Test that summaries are formatted correctly for prompts"""
        from core.retriever import MemoryRetriever
        
        # This would need mocking of dependencies
        # TODO: Implement test
        pass
    
    def test_format_conversations_for_prompt(self):
        """Test that conversations are formatted correctly for prompts"""
        # TODO: Implement test
        pass


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
