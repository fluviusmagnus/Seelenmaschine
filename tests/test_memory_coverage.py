"""Targeted tests for Memory Manager - Focusing on uncovered methods

This module tests methods not covered by existing tests to increase coverage.
"""

import json
from unittest.mock import Mock, patch

import pytest


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
        embedding_client.get_embedding_async.return_value = [0.1] * 1536
        
        reranker_client = Mock()
        
        return {
            'db': db,
            'embedding_client': embedding_client,
            'reranker_client': reranker_client,
        }
    
    def test_reset_session(self, mock_dependencies):
        """Test reset_session method"""
        from memory.manager import MemoryManager
        
        with patch('memory.manager.ContextWindow') as mock_ctx_class:
            with patch('core.config.Config.CONTEXT_WINDOW_TRIGGER_SUMMARY', 24):
                with patch('core.config.Config.CONTEXT_WINDOW_KEEP_MIN', 12):
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
        from memory.manager import MemoryManager
        
        with patch('memory.manager.ContextWindow') as mock_ctx_class:
            with patch('memory.manager.VectorRetriever'):
                with patch('core.config.Config.CONTEXT_WINDOW_TRIGGER_SUMMARY', 24):
                    with patch('core.config.Config.CONTEXT_WINDOW_KEEP_MIN', 12):
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
                        conversation_id, embedding = mm.add_user_message(
                            "Hello, this is a test message"
                        )
                        
                        # Verify conversation was inserted
                        assert conversation_id == 100
                        assert embedding == [0.1] * 1536
                        mock_dependencies['db'].insert_conversation.assert_called_once()
    
    def test_add_assistant_message(self, mock_dependencies):
        """Test add_assistant_message method"""
        from memory.manager import MemoryManager
        
        with patch('memory.manager.ContextWindow') as mock_ctx_class:
            with patch('memory.manager.VectorRetriever'):
                with patch('core.config.Config.CONTEXT_WINDOW_TRIGGER_SUMMARY', 24):
                    with patch('core.config.Config.CONTEXT_WINDOW_KEEP_MIN', 12):
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
        embedding_client.get_embedding.return_value = [0.1] * 1536
        embedding_client.get_embedding_async.return_value = [0.1] * 1536
        reranker_client = Mock()
        
        return {
            'db': db,
            'embedding_client': embedding_client,
            'reranker_client': reranker_client,
        }
    
    def test_get_context_messages(self, mock_dependencies):
        """Test get_context_messages method"""
        from memory.manager import MemoryManager
        
        with patch('memory.manager.ContextWindow') as mock_ctx_class:
            with patch('core.config.Config.CONTEXT_WINDOW_TRIGGER_SUMMARY', 24):
                with patch('core.config.Config.CONTEXT_WINDOW_KEEP_MIN', 12):
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
        from memory.manager import MemoryManager
        
        with patch('memory.manager.ContextWindow') as mock_ctx_class:
            with patch('core.config.Config.CONTEXT_WINDOW_TRIGGER_SUMMARY', 24):
                with patch('core.config.Config.CONTEXT_WINDOW_KEEP_MIN', 12):
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

    @pytest.fixture
    def memory_manager(self):
        """Create a minimal MemoryManager instance for utility-method tests."""
        from memory.manager import MemoryManager

        db = Mock()
        db.get_active_session.return_value = {"session_id": 1}
        db.get_summaries_by_session.return_value = []
        db.get_unsummarized_conversations.return_value = []

        embedding_client = Mock()
        reranker_client = Mock()

        return MemoryManager(db, embedding_client, reranker_client)
    
    def test_clean_json_response(self, memory_manager):
        """Test _clean_json_response method"""
        raw_response = "```json\n{\"bot\": {\"name\": \"TestBot\"}}\n```"

        cleaned = memory_manager._clean_json_response(raw_response)

        assert cleaned == "{\"bot\": {\"name\": \"TestBot\"}}"
    
    def test_validate_seele_structure_valid(self, memory_manager):
        """Test _validate_seele_structure with valid data"""
        valid_data = {
            "bot": {"name": "TestBot"},
            "user": {"name": "TestUser", "location": ""},
            "memorable_events": {},
            "commands_and_agreements": [],
        }

        assert memory_manager._validate_seele_structure(valid_data) is True
    
    def test_validate_seele_structure_invalid(self, memory_manager):
        """Test _validate_seele_structure with invalid data"""
        invalid_data = {}

        assert memory_manager._validate_seele_structure(invalid_data) is False


class TestSeeleRepairPaths:
    """Test LLM-driven persisted seele.json repair flows."""

    def test_ensure_seele_schema_current_repairs_malformed_json(self, tmp_path, monkeypatch):
        """Malformed persisted JSON should trigger the shared LLM repair path."""
        from core.config import Config
        from memory.seele import Seele

        seele_path = tmp_path / "seele.json"
        seele_path.write_text('{"bot": {oops}}', encoding="utf-8")

        monkeypatch.setattr(Config, "SEELE_JSON_PATH", seele_path)

        seele = Seele(db=None)

        with patch.object(seele, "_repair_persisted_seele_json", return_value=True) as mock_repair:
            result = seele.ensure_seele_schema_current("test runtime repair")

        assert result is True
        mock_repair.assert_called_once()
        assert "malformed JSON" in mock_repair.call_args.kwargs["error_message"]
        assert mock_repair.call_args.kwargs["repair_context"] == "test runtime repair"

    def test_ensure_seele_schema_current_repairs_legacy_structure(self, tmp_path, monkeypatch):
        """Legacy list-based memorable_events should trigger LLM repair instead of mechanical migration."""
        from core.config import Config
        from memory.seele import Seele

        seele_path = tmp_path / "seele.json"
        seele_path.write_text(
            '{"bot": {}, "user": {}, "memorable_events": [], "commands_and_agreements": []}',
            encoding="utf-8",
        )

        monkeypatch.setattr(Config, "SEELE_JSON_PATH", seele_path)

        seele = Seele(db=None)

        with patch.object(seele, "_repair_persisted_seele_json", return_value=True) as mock_repair:
            result = seele.ensure_seele_schema_current("test migration repair")

        assert result is True
        mock_repair.assert_called_once()
        assert "legacy or non-canonical structure" in mock_repair.call_args.kwargs["error_message"]

    def test_repair_persisted_seele_json_writes_repaired_result(self, tmp_path, monkeypatch):
        """LLM repair should persist the repaired complete seele.json output."""
        from core.config import Config
        from memory.seele import Seele

        seele_path = tmp_path / "seele.json"
        monkeypatch.setattr(Config, "SEELE_JSON_PATH", seele_path)

        repaired_output = json.dumps(
            {
                "bot": {
                    "name": "TestBot",
                    "gender": "neutral",
                    "birthday": "2025-02-15",
                    "role": "AI assistant",
                    "appearance": "",
                    "likes": [],
                    "dislikes": [],
                    "language_style": {"description": "", "examples": []},
                    "personality": {
                        "mbti": "",
                        "description": "",
                        "worldview_and_values": "",
                    },
                    "emotions": {"long_term": "", "short_term": ""},
                    "needs": {"long_term": "", "short_term": ""},
                    "relationship_with_user": "",
                },
                "user": {
                    "name": "TestUser",
                    "gender": "",
                    "birthday": "",
                    "location": "",
                    "personal_facts": [],
                    "abilities": [],
                    "likes": [],
                    "dislikes": [],
                    "personality": {
                        "mbti": "",
                        "description": "",
                        "worldview_and_values": "",
                    },
                    "emotions": {"long_term": "", "short_term": ""},
                    "needs": {"long_term": "", "short_term": ""},
                },
                "memorable_events": {},
                "commands_and_agreements": [],
            }
        )

        seele = Seele(db=None)

        fake_client = Mock()
        fake_client.generate_seele_repair.return_value = repaired_output
        fake_client.close = Mock()

        with patch("llm.chat_client.LLMClient", return_value=fake_client):
            result = seele._repair_persisted_seele_json(
                repair_context="unit test",
                error_message="needs repair",
                current_content='{"broken": true}',
            )

        assert result is True
        assert seele_path.exists()
        saved = json.loads(seele_path.read_text(encoding="utf-8"))
        assert saved["bot"]["name"] == "TestBot"
        assert saved["user"]["name"] == "TestUser"
        assert saved["user"]["location"] == ""


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
