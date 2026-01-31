"""Targeted tests for Memory Manager - Focusing on uncovered methods

This module tests methods not covered by existing tests to increase coverage.
"""

import sys
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
import pytest
import json

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestMemoryManagerSessionOperations:
    """Test session operations not covered by existing tests"""
    
    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies"""
        db = Mock()
        db.get_active_session.return_value = {"session_id": 1}
        db.get_summaries_by_session.return_value = []
        db.get_unsummarized_conversations.return_value = []
        db.create_session.return_value = 2
        db.close_session = Mock()
        db.delete_session = Mock()
        
        embedding_client = Mock()
        embedding_client.get_embedding.return_value = [0.1] * 1536
        
        reranker_client = Mock()
        
        return {
            'db': db,
            'embedding_client': embedding_client,
            'reranker_client': reranker_client,
        }
    
    def test_reset_session(self, mock_dependencies):
        """Test reset_session method"""
        from core.memory import MemoryManager
        
        with patch('core.memory.ContextWindow') as mock_ctx_class:
            with patch('config.Config.CONTEXT_WINDOW_TRIGGER_SUMMARY', 24):
                with patch('config.Config.CONTEXT_WINDOW_KEEP_MIN', 12):
                    mock_ctx = Mock()
                    mock_ctx.get_recent_summary_ids = Mock(return_value=[])
                    mock_ctx.add_summary = Mock()
                    mock_ctx.add_message = Mock()
                    mock_ctx.clear = Mock()
                    mock_ctx_class.return_value = mock_ctx
                    
                    mm = MemoryManager(
                        db=mock_dependencies['db'],
                        embedding_client=mock_dependencies['embedding_client'],
                        reranker_client=mock_dependencies['reranker_client']
                    )
                    
                    # Reset session
                    mm.reset_session()
                    
                    # Verify session was deleted
                    mock_dependencies['db'].delete_session.assert_called_once_with(1)


class TestMemoryManagerMessageOperations:
    """Test message operations"""
    
    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies"""
        db = Mock()
        db.get_active_session.return_value = {"session_id": 1}
        db.get_summaries_by_session.return_value = []
        db.get_unsummarized_conversations.return_value = []
        db.insert_conversation.return_value = 100
        db.insert_summary.return_value = 200
        
        embedding_client = Mock()
        embedding_client.get_embedding.return_value = [0.1] * 1536
        
        reranker_client = Mock()
        
        return {
            'db': db,
            'embedding_client': embedding_client,
            'reranker_client': reranker_client,
        }
    
    def test_add_user_message(self, mock_dependencies):
        """Test add_user_message method"""
        from core.memory import MemoryManager
        
        with patch('core.memory.ContextWindow') as mock_ctx_class:
            with patch('core.memory.MemoryRetriever'):
                with patch('config.Config.CONTEXT_WINDOW_TRIGGER_SUMMARY', 24):
                    with patch('config.Config.CONTEXT_WINDOW_KEEP_MIN', 12):
                        mock_ctx = Mock()
                        mock_ctx.get_recent_summary_ids = Mock(return_value=[])
                        mock_ctx.add_message = Mock()
                        mock_ctx_class.return_value = mock_ctx
                        
                        mm = MemoryManager(
                            db=mock_dependencies['db'],
                            embedding_client=mock_dependencies['embedding_client'],
                            reranker_client=mock_dependencies['reranker_client']
                        )
                        
                        # Add user message
                        conversation_id = mm.add_user_message("Hello, this is a test message")
                        
                        # Verify conversation was inserted
                        assert conversation_id == 100
                        mock_dependencies['db'].insert_conversation.assert_called_once()
    
    def test_add_assistant_message(self, mock_dependencies):
        """Test add_assistant_message method"""
        from core.memory import MemoryManager
        
        with patch('core.memory.ContextWindow') as mock_ctx_class:
            with patch('core.memory.MemoryRetriever'):
                with patch('config.Config.CONTEXT_WINDOW_TRIGGER_SUMMARY', 24):
                    with patch('config.Config.CONTEXT_WINDOW_KEEP_MIN', 12):
                        mock_ctx = Mock()
                        mock_ctx.get_recent_summary_ids = Mock(return_value=[])
                        mock_ctx.add_message = Mock()
                        mock_ctx.get_total_message_count = Mock(return_value=0)
                        mock_ctx_class.return_value = mock_ctx
                        
                        mm = MemoryManager(
                            db=mock_dependencies['db'],
                            embedding_client=mock_dependencies['embedding_client'],
                            reranker_client=mock_dependencies['reranker_client']
                        )
                        
                        # Add assistant message
                        conversation_id, summary_id = mm.add_assistant_message("This is a response")
                        
                        # Verify conversation was inserted
                        assert conversation_id == 100
                        mock_dependencies['db'].insert_conversation.assert_called_once()


class TestMemoryManagerUtilityMethods:
    """Test utility/helper methods"""
    
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
    
    def test_get_context_messages(self, mock_dependencies):
        """Test get_context_messages method"""
        from core.memory import MemoryManager
        
        with patch('core.memory.ContextWindow') as mock_ctx_class:
            with patch('config.Config.CONTEXT_WINDOW_TRIGGER_SUMMARY', 24):
                with patch('config.Config.CONTEXT_WINDOW_KEEP_MIN', 12):
                    mock_ctx = Mock()
                    mock_ctx.get_recent_summary_ids = Mock(return_value=[])
                    mock_ctx.get_context_as_messages = Mock(return_value=[
                        {"role": "user", "text": "Hello"},
                        {"role": "assistant", "text": "Hi there"}
                    ])
                    mock_ctx_class.return_value = mock_ctx
                    
                    mm = MemoryManager(
                        db=mock_dependencies['db'],
                        embedding_client=mock_dependencies['embedding_client'],
                        reranker_client=mock_dependencies['reranker_client']
                    )
                    
                    # Get context messages
                    messages = mm.get_context_messages()
                    
                    # Verify messages were returned
                    assert isinstance(messages, list)
                    assert len(messages) == 2
    
    def test_get_recent_summaries(self, mock_dependencies):
        """Test get_recent_summaries method"""
        from core.memory import MemoryManager
        
        with patch('core.memory.ContextWindow') as mock_ctx_class:
            with patch('config.Config.CONTEXT_WINDOW_TRIGGER_SUMMARY', 24):
                with patch('config.Config.CONTEXT_WINDOW_KEEP_MIN', 12):
                    mock_ctx = Mock()
                    mock_ctx.get_recent_summary_ids = Mock(return_value=[])
                    mock_ctx.get_recent_summaries_as_text = Mock(return_value=[
                        "Summary 1",
                        "Summary 2"
                    ])
                    mock_ctx_class.return_value = mock_ctx
                    
                    mm = MemoryManager(
                        db=mock_dependencies['db'],
                        embedding_client=mock_dependencies['embedding_client'],
                        reranker_client=mock_dependencies['reranker_client']
                    )
                    
                    # Get recent summaries
                    summaries = mm.get_recent_summaries()
                    
                    # Verify summaries were returned
                    assert isinstance(summaries, list)
                    assert len(summaries) == 2


class TestMemoryManagerJsonUtils:
    """Test JSON utility methods"""
    
    def test_clean_json_response(self):
        """Test _clean_json_response method"""
        from core.memory import MemoryManager
        
        # Create a mock MemoryManager to test the static method
        mm = Mock(spec=MemoryManager)
        
        # Test cases for JSON cleaning would go here
        # This is a placeholder for the actual test
        pass
    
    def test_validate_seele_structure_valid(self):
        """Test _validate_seele_structure with valid data"""
        from core.memory import MemoryManager
        
        # Test with valid seele structure
        valid_data = {
            "bot": {"name": "TestBot"},
            "user": {"name": "TestUser"}
        }
        
        # This would test the validation logic
        pass
    
    def test_validate_seele_structure_invalid(self):
        """Test _validate_seele_structure with invalid data"""
        from core.memory import MemoryManager
        
        # Test with invalid seele structure
        invalid_data = {}
        
        # This would test the validation logic
        pass


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
