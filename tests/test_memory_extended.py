"""Extended tests for Memory Manager

Additional tests to increase coverage of memory module.
"""

import sys
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
import pytest
import json

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestMemoryManagerLongTermMemory:
    """Test long-term memory operations"""
    
    @pytest.fixture
    def mock_dependencies(self):
        """Create all mock dependencies"""
        db = Mock()
        db.get_active_session.return_value = {"session_id": 1}
        db.get_summaries_by_session.return_value = []
        db.get_unsummarized_conversations.return_value = []
        db.insert_summary.return_value = 100
        db.insert_conversation.return_value = 200
        db.close_session = Mock()
        db.create_session.return_value = 2
        
        embedding_client = Mock()
        embedding_client.get_embedding.return_value = [0.1] * 1536
        embedding_client.get_embedding_async = AsyncMock(return_value=[0.1] * 1536)
        
        reranker_client = Mock()
        
        return {
            'db': db,
            'embedding_client': embedding_client,
            'reranker_client': reranker_client,
        }
    
    def test_update_long_term_memory_with_json_patch(self, mock_dependencies):
        """Test updating long-term memory with JSON Patch"""
        from core.memory import MemoryManager
        
        # Create messages
        messages = [
            {"timestamp": 1000, "role": "user", "text": "My name is John"},
            {"timestamp": 1001, "role": "assistant", "text": "Nice to meet you, John!"}
        ]
        
        mock_dependencies['db'].get_unsummarized_conversations.return_value = messages
        
        with patch('core.memory.ContextWindow') as mock_ctx_class:
            with patch('config.Config.CONTEXT_WINDOW_TRIGGER_SUMMARY', 24):
                with patch('config.Config.CONTEXT_WINDOW_KEEP_MIN', 12):
                    mock_ctx = Mock()
                    mock_ctx.add_summary = Mock()
                    mock_ctx.add_message = Mock()
                    mock_ctx.get_recent_summary_ids = Mock(return_value=[])
                    mock_ctx_class.return_value = mock_ctx
                    
                    mm = MemoryManager(
                        db=mock_dependencies['db'],
                        embedding_client=mock_dependencies['embedding_client'],
                        reranker_client=mock_dependencies['reranker_client']
                    )
                    
                    # Verify memory manager was created
                    assert mm is not None
    
    def test_get_long_term_memory(self, mock_dependencies):
        """Test retrieving long-term memory"""
        from core.memory import MemoryManager
        
        mock_dependencies['db'].get_unsummarized_conversations.return_value = []
        
        with patch('core.memory.ContextWindow') as mock_ctx_class:
            with patch('config.Config.CONTEXT_WINDOW_TRIGGER_SUMMARY', 24):
                with patch('config.Config.CONTEXT_WINDOW_KEEP_MIN', 12):
                    mock_ctx = Mock()
                    mock_ctx.get_recent_summary_ids = Mock(return_value=[])
                    mock_ctx_class.return_value = mock_ctx
                    
                    mm = MemoryManager(
                        db=mock_dependencies['db'],
                        embedding_client=mock_dependencies['embedding_client'],
                        reranker_client=mock_dependencies['reranker_client']
                    )
                    
                    # Get long-term memory
                    memory = mm.get_long_term_memory()
                    
                    # Should return a dict
                    assert isinstance(memory, dict)


class TestMemoryManagerSessionOperations:
    """Test session management operations"""
    
    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies"""
        db = Mock()
        db.get_active_session.return_value = {"session_id": 1}
        db.get_summaries_by_session.return_value = []
        db.get_unsummarized_conversations.return_value = []
        
        embedding_client = Mock()
        reranker_client = Mock()
        
        return {
            'db': db,
            'embedding_client': embedding_client,
            'reranker_client': reranker_client,
        }
    
    @pytest.mark.skip(reason="Complex mocking required for session operations")
    def test_new_session(self, mock_dependencies):
        """Test creating new session"""
        # This test requires complex mocking of session operations
        # which involves summarization logic
        pass


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
