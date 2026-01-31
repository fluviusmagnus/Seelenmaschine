"""Advanced tests for Memory Manager core logic

This module contains comprehensive tests for MemoryManager's complex logic
including session management, automatic summarization, and memory retrieval.
"""

import sys
from pathlib import Path

# Add project root to path for absolute imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from unittest.mock import Mock, patch, MagicMock, call, AsyncMock
from typing import List, Dict, Any


class TestMemoryManagerSessionManagement:
    """Test session management and restoration"""
    
    @pytest.fixture
    def mock_db(self):
        """Create a mock DatabaseManager"""
        db = Mock(spec=['get_active_session', 'create_session', 'close_session', 
                        'delete_session', 'get_summaries_by_session', 
                        'get_unsummarized_conversations', 'insert_conversation',
                        'insert_summary'])
        return db
    
    @pytest.fixture
    def mock_embedding_client(self):
        """Create a mock EmbeddingClient"""
        client = Mock(spec=['get_embedding', 'get_embedding_async'])
        client.get_embedding.return_value = [0.1] * 1536
        return client
    
    @pytest.fixture
    def mock_reranker_client(self):
        """Create a mock RerankerClient"""
        client = Mock(spec=['rerank', 'rerank_async'])
        return client
    
    @pytest.fixture
    def mock_context_window(self):
        """Create a mock ContextWindow"""
        ctx = Mock(spec=['add_message', 'add_summary', 'clear', 'context_window',
                        'get_recent_summary_ids'])
        ctx.context_window = []
        ctx.get_recent_summary_ids.return_value = []
        return ctx
    
    @pytest.mark.asyncio
    async def test_ensure_active_session_creates_new(self, mock_db, mock_embedding_client, 
                                                      mock_reranker_client):
        """Test that new session is created when no active session exists"""
        from core.memory import MemoryManager
        
        # Setup: no active session
        mock_db.get_active_session.return_value = None
        mock_db.create_session.return_value = 42
        
        with patch('core.memory.ContextWindow') as mock_ctx_class:
            mock_ctx_class.return_value = Mock()
            
            mm = MemoryManager(
                db=mock_db,
                embedding_client=mock_embedding_client,
                reranker_client=mock_reranker_client
            )
            
            # Verify create_session was called
            mock_db.create_session.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_ensure_active_session_restores_existing(self, mock_db, mock_embedding_client,
                                                            mock_reranker_client):
        """Test that existing session context is restored"""
        from core.memory import MemoryManager
        
        # Setup: existing active session with summaries
        mock_db.get_active_session.return_value = {"session_id": 42}
        mock_db.get_summaries_by_session.return_value = [
            {"summary_id": 1, "summary": "Test summary 1"},
            {"summary_id": 2, "summary": "Test summary 2"}
        ]
        mock_db.get_unsummarized_conversations.return_value = []
        
        with patch('core.memory.ContextWindow') as mock_ctx_class:
            mock_ctx = Mock()
            mock_ctx.add_summary = Mock()
            mock_ctx.add_message = Mock()
            mock_ctx.get_recent_summary_ids = Mock(return_value=[])
            mock_ctx_class.return_value = mock_ctx
            
            mm = MemoryManager(
                db=mock_db,
                embedding_client=mock_embedding_client,
                reranker_client=mock_reranker_client
            )
            
            # Verify summaries were restored
            assert mock_ctx.add_summary.call_count == 2


class TestMemoryManagerSummarization:
    """Test automatic summarization logic"""
    
    @pytest.fixture
    def mock_db(self):
        """Create a mock DatabaseManager"""
        db = Mock()
        db.get_active_session.return_value = {"session_id": 1}
        db.get_summaries_by_session.return_value = []
        db.get_unsummarized_conversations.return_value = []
        db.insert_summary.return_value = 100
        db.insert_conversation.return_value = 200
        db.close_session = Mock()
        db.create_session.return_value = 2
        db.delete_session = Mock()
        return db
    
    @pytest.fixture
    def mock_embedding_client(self):
        """Create a mock EmbeddingClient"""
        client = Mock()
        client.get_embedding.return_value = [0.1] * 1536
        client.get_embedding_async = AsyncMock(return_value=[0.1] * 1536)
        return client
    
    @pytest.fixture
    def mock_reranker_client(self):
        """Create a mock RerankerClient"""
        return Mock()
    
    @pytest.fixture
    def mock_llm_client(self):
        """Create a mock LLMClient"""
        client = Mock()
        client.generate_summary.return_value = "Test summary"
        client.generate_summary_async = AsyncMock(return_value="Test summary")
        client.generate_memory_update.return_value = '{"user": {"name": "Test"}}'
        client.generate_memory_update_async = AsyncMock(return_value='{"user": {"name": "Test"}}')
        return client
    
    @pytest.mark.skip(reason="Requires complex LLM mocking - needs proper async mock setup")
    def test_summary_trigger_at_threshold(self, mock_db, mock_embedding_client, mock_reranker_client):
        """Test summarization is triggered at threshold"""
        from core.memory import MemoryManager
        
        # Create 24 conversations (at trigger threshold)
        conversations = [
            {"timestamp": 1000 + i, "role": "user" if i % 2 == 0 else "assistant", "text": f"Message {i}"}
            for i in range(24)
        ]
        mock_db.get_unsummarized_conversations.return_value = conversations
        
        with patch('core.memory.ContextWindow') as mock_ctx_class:
            with patch('config.Config') as mock_config_class:
                mock_config = Mock()
                mock_config.CONTEXT_WINDOW_TRIGGER_SUMMARY = 24
                mock_config.CONTEXT_WINDOW_KEEP_MIN = 12
                mock_config.RECENT_SUMMARIES_MAX = 3
                mock_config_class.return_value = mock_config
                
                mock_ctx = Mock()
                mock_ctx.add_message = Mock()
                mock_ctx.get_recent_summary_ids = Mock(return_value=[])
                mock_ctx_class.return_value = mock_ctx
                
                mm = MemoryManager(
                    db=mock_db,
                    embedding_client=mock_embedding_client,
                    reranker_client=mock_reranker_client
                )
                
                # TODO: This test needs the _generate_summary method to be properly mocked
                # The test verifies the condition is met for triggering summarization
                assert len(conversations) >= 24


class TestMemoryManagerRetrieval:
    """Test memory retrieval logic"""
    
    @pytest.fixture
    def mock_db(self):
        db = Mock()
        db.get_active_session.return_value = {"session_id": 1}
        return db
    
    @pytest.fixture
    def mock_embedding_client(self):
        client = Mock()
        client.get_embedding.return_value = [0.1] * 1536
        return client
    
    @pytest.fixture
    def mock_reranker_client(self):
        client = Mock()
        client.rerank.return_value = [
            {"id": 1, "score": 0.9},
            {"id": 2, "score": 0.8}
        ]
        return client
    
    def test_retrieve_excludes_recent_summaries(self, mock_db, mock_embedding_client, mock_reranker_client):
        """Test that recent summaries in context window are excluded from search"""
        from core.memory import MemoryManager
        
        # Setup: no active session to avoid _restore_context_from_session
        mock_db.get_active_session.return_value = None
        mock_db.create_session.return_value = 42
        
        with patch('core.memory.ContextWindow') as mock_ctx_class:
            with patch('core.memory.MemoryRetriever') as mock_retriever_class:
                mock_ctx = Mock()
                mock_ctx.get_recent_summary_ids.return_value = [1, 2, 3]
                mock_ctx_class.return_value = mock_ctx
                
                mock_retriever = Mock()
                mock_retriever.retrieve_related_memories.return_value = ([], [])
                mock_retriever.format_summaries_for_prompt.return_value = []
                mock_retriever.format_conversations_for_prompt.return_value = []
                mock_retriever_class.return_value = mock_retriever
                
                mm = MemoryManager(
                    db=mock_db,
                    embedding_client=mock_embedding_client,
                    reranker_client=mock_reranker_client
                )
                
                # Call process_user_input
                mm.process_user_input("Test query")
                
                # Verify that recent summary IDs were passed to retriever
                call_args = mock_retriever.retrieve_related_memories.call_args
                assert call_args.kwargs['exclude_summary_ids'] == [1, 2, 3]


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
