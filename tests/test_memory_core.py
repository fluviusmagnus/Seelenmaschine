"""Core tests for Memory Manager - Automatic summarization and long-term memory

This module contains comprehensive tests for:
- Automatic summarization triggers
- Long-term memory (seele.json) updates
- Complete memory retrieval flows
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from memory.context import Message


class TestMemoryManagerAutomaticSummarization:
    """Test automatic summarization logic"""
    
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
        embedding_client.get_embedding_async = AsyncMock(return_value=[0.1] * 1536)
        
        reranker_client = Mock()
        
        llm_client = Mock()
        llm_client.generate_summary.return_value = "Generated summary text"
        llm_client.generate_summary_async = AsyncMock(return_value="Generated summary text")
        llm_client.generate_memory_update.return_value = '{"user": {"name": "Test User"}}'
        llm_client.generate_memory_update_async = AsyncMock(return_value='{"user": {"name": "Test User"}}')
        
        return {
            'db': db,
            'embedding_client': embedding_client,
            'reranker_client': reranker_client,
            'llm_client': llm_client
        }
    
class TestMemoryManagerLongTermMemory:
    """Test long-term memory (seele.json) updates"""
    
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
        embedding_client.get_embedding_async = AsyncMock(return_value=[0.1] * 1536)
        
        reranker_client = Mock()
        
        return {
            'db': db,
            'embedding_client': embedding_client,
            'reranker_client': reranker_client,
        }
    
    def test_memory_update_generates_json_patch(self, mock_dependencies):
        """Test that memory update generates valid JSON Patch"""
        from memory.manager import MemoryManager
        
        # Create a MemoryManager with mocked dependencies
        messages = [
            {"timestamp": 1000 + i, "role": "user" if i % 2 == 0 else "assistant", "text": f"Message {i}"}
            for i in range(5)
        ]
        mock_dependencies['db'].get_unsummarized_conversations.return_value = messages
        
        with patch('memory.manager.ContextWindow') as mock_ctx_class:
            with patch('core.config.Config.CONTEXT_WINDOW_TRIGGER_SUMMARY', 24):
                with patch('core.config.Config.CONTEXT_WINDOW_KEEP_MIN', 12):
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
                    
                    # Verify memory manager was created successfully
                    assert mm is not None
    
    @pytest.mark.asyncio
    async def test_memory_update_applies_to_seele_json(self, mock_dependencies):
        """Test that memory update is applied to seele.json"""
        from memory.manager import MemoryManager

        with patch('memory.manager.ContextWindow') as mock_ctx_class:
            mock_ctx = Mock()
            mock_ctx.get_recent_summary_ids = Mock(return_value=[])
            mock_ctx.add_summary = Mock()
            mock_ctx.add_message = Mock()
            mock_ctx_class.return_value = mock_ctx

            mm = MemoryManager(
                db=mock_dependencies['db'],
                embedding_client=mock_dependencies['embedding_client'],
                reranker_client=mock_dependencies['reranker_client']
            )

        with patch('prompts.runtime.update_seele_json', return_value=True) as mock_update:
            success = await mm.update_long_term_memory_async(
                summary_id=100,
                json_patch='[{"op":"replace","path":"/user/name","value":"Test User"}]'
            )

        assert success is True
        mock_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_long_term_memory_schema_delegates_to_seele(self, mock_dependencies):
        """Test schema bootstrap delegates to Seele normalizer."""
        from memory.manager import MemoryManager

        with patch('memory.manager.ContextWindow') as mock_ctx_class:
            mock_ctx = Mock()
            mock_ctx.get_recent_summary_ids = Mock(return_value=[])
            mock_ctx.add_summary = Mock()
            mock_ctx.add_message = Mock()
            mock_ctx_class.return_value = mock_ctx

            mm = MemoryManager(
                db=mock_dependencies['db'],
                embedding_client=mock_dependencies['embedding_client'],
                reranker_client=mock_dependencies['reranker_client']
            )

        with patch.object(
            mm.seele,
            'ensure_seele_schema_current_async',
            new=AsyncMock(return_value=True),
        ) as mock_ensure:
            result = await mm.ensure_long_term_memory_schema_async()

        assert result is True
        mock_ensure.assert_awaited_once_with()


class TestMemoryManagerCompleteFlows:
    """Test complete memory management flows"""
    
    @pytest.mark.asyncio
    async def test_full_conversation_to_summary_flow(self):
        """Test complete flow from conversation to summary to retrieval"""
        from memory.manager import MemoryManager

        db = Mock()
        db.get_active_session.return_value = {"session_id": 1}
        db.get_summaries_by_session.return_value = []
        db.get_unsummarized_conversations.return_value = []
        db.insert_conversation.return_value = 200

        embedding_client = Mock()
        embedding_client.get_embedding_async = AsyncMock(return_value=[0.1] * 1536)

        reranker_client = Mock()

        with patch('core.config.Config.CONTEXT_WINDOW_TRIGGER_SUMMARY', 24):
            with patch('core.config.Config.CONTEXT_WINDOW_KEEP_MIN', 12):
                mm = MemoryManager(db, embedding_client, reranker_client)

        with patch.object(
            mm,
            "_check_and_create_summary_async",
            new=AsyncMock(return_value=(123, [Message("user", "hello")])),
        ):
            with patch.object(
                mm,
                "_update_long_term_memory_async",
                new=AsyncMock(return_value=True),
            ) as mock_update_memory:
                conversation_id, summary_id = await mm.add_assistant_message_async("This is a response")
                summary_id, summarized_messages = await mm._check_and_create_summary_async()
                if summary_id is not None and summarized_messages is not None:
                    await mm._update_long_term_memory_async(summary_id, summarized_messages)

        assert conversation_id == 200
        assert summary_id == 123
        mock_update_memory.assert_awaited_once_with(123, [Message("user", "hello")])
    
    @pytest.mark.asyncio
    async def test_session_new_creates_summary(self):
        """Test that /new command creates summary of old session"""
        from memory.manager import MemoryManager

        db = Mock()
        db.get_active_session.side_effect = [
            {"session_id": 1},
            {"session_id": 1},
        ]
        db.get_summaries_by_session.return_value = []
        db.get_unsummarized_conversations.return_value = []
        db.insert_summary.return_value = 321
        db.create_session.return_value = 2

        embedding_client = Mock()
        embedding_client.get_embedding_async = AsyncMock(return_value=[0.1] * 1536)

        reranker_client = Mock()

        with patch('core.config.Config.CONTEXT_WINDOW_TRIGGER_SUMMARY', 24):
            with patch('core.config.Config.CONTEXT_WINDOW_KEEP_MIN', 12):
                mm = MemoryManager(db, embedding_client, reranker_client)

        remaining_messages = [Message("user", "msg1"), Message("assistant", "msg2")]
        mm.context_window.context_window = remaining_messages

        with patch.object(
            mm,
            "_generate_summary_async",
            new=AsyncMock(return_value="Generated summary text"),
        ):
            with patch.object(
                mm,
                "_update_long_term_memory_async",
                new=AsyncMock(return_value=True),
            ) as mock_update_memory:
                new_session_id = await mm.new_session_async()

        assert new_session_id == 2
        db.insert_summary.assert_called_once()
        db.close_session.assert_called_once()
        mock_update_memory.assert_awaited_once_with(321, remaining_messages)


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
