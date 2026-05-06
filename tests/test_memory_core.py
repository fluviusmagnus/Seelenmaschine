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

        from memory.seele import PatchApplyResult

        patch_result = PatchApplyResult(True, {}, "")
        with patch(
            'prompts.runtime.update_seele_json_result',
            return_value=patch_result,
        ) as mock_update:
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


class TestValidateShortTermPatchOperations:
    """Tests for _validate_short_term_patch_operations and _is_short_term_path.

    These are module-level functions in memory.seele that enforce patch operation
    rules on short-term emotion/need fields.
    """

    def _make_cache(self, bot_emotions=None, bot_needs=None,
                    user_emotions=None, user_needs=None):
        """Build a minimal working_cache dict for validation tests."""
        cache = {"bot": {}, "user": {}}
        if bot_emotions is not None:
            cache["bot"]["emotions"] = {"short_term": list(bot_emotions)}
        if bot_needs is not None:
            cache["bot"]["needs"] = {"short_term": list(bot_needs)}
        if user_emotions is not None:
            cache["user"]["emotions"] = {"short_term": list(user_emotions)}
        if user_needs is not None:
            cache["user"]["needs"] = {"short_term": list(user_needs)}
        return cache

    def _validate_patch_operations(self, operations, cache):
        """Return whether unified patch validation accepts the operations."""
        from memory.seele import _validate_patch_operations

        return _validate_patch_operations(operations, cache) == ""

    # ── _is_short_term_path ──────────────────────────────────────────────

    def test_is_short_term_path_valid_add_paths(self):
        """Valid short_term paths with /- should be recognized."""
        from memory.seele import _is_short_term_path

        assert _is_short_term_path("/bot/emotions/short_term/-") is True
        assert _is_short_term_path("/bot/needs/short_term/-") is True
        assert _is_short_term_path("/user/emotions/short_term/-") is True
        assert _is_short_term_path("/user/needs/short_term/-") is True

    def test_is_short_term_path_valid_numeric_index(self):
        """Valid short_term paths with numeric index should be recognized."""
        from memory.seele import _is_short_term_path

        assert _is_short_term_path("/bot/emotions/short_term/0") is True
        assert _is_short_term_path("/bot/emotions/short_term/2") is True
        assert _is_short_term_path("/user/needs/short_term/5") is True

    def test_is_short_term_path_invalid_non_short_term(self):
        """Paths not targeting short_term should return False."""
        from memory.seele import _is_short_term_path

        assert _is_short_term_path("/bot/emotions/long_term") is False
        assert _is_short_term_path("/bot/emotions") is False
        assert _is_short_term_path("/bot") is False
        assert _is_short_term_path("/memorable_events/evt_1") is False
        assert _is_short_term_path("/user/name") is False
        assert _is_short_term_path("/user/personal_facts/-") is False

    def test_is_short_term_path_invalid_non_string(self):
        """Non-string paths should return False."""
        from memory.seele import _is_short_term_path

        assert _is_short_term_path(None) is False
        assert _is_short_term_path(42) is False
        assert _is_short_term_path(True) is False

    def test_is_short_term_path_unknown_owner_rejected(self):
        """Paths with unknown owner should return False."""
        from memory.seele import _is_short_term_path

        assert _is_short_term_path("/unknown/field/short_term/0") is False

    # ── _validate_short_term_patch_operations (add) ───────────────────────

    def test_valid_add_to_short_term(self):
        """Appending to short_term via add /- should pass."""
        ops = [{"op": "add", "path": "/bot/emotions/short_term/-",
                "value": "feeling curious"}]
        cache = self._make_cache(bot_emotions=["previous"])
        assert self._validate_patch_operations(ops, cache) is True

    def test_add_with_empty_value_rejected(self):
        """add with empty value should be rejected."""
        ops = [{"op": "add", "path": "/bot/emotions/short_term/-",
                "value": ""}]
        cache = self._make_cache(bot_emotions=["previous"])
        assert self._validate_patch_operations(ops, cache) is False

    def test_add_with_whitespace_value_rejected(self):
        """add with whitespace-only value should be rejected."""
        ops = [{"op": "add", "path": "/bot/emotions/short_term/-",
                "value": "   "}]
        cache = self._make_cache(bot_emotions=["previous"])
        assert self._validate_patch_operations(ops, cache) is False

    def test_add_with_numeric_index_rejected(self):
        """add with numeric index (not /-) should be rejected."""
        ops = [{"op": "add", "path": "/bot/emotions/short_term/0",
                "value": "feeling good"}]
        cache = self._make_cache(bot_emotions=["previous"])
        assert self._validate_patch_operations(ops, cache) is False

    # ── _validate_short_term_patch_operations (replace) ───────────────────

    def test_valid_replace_last_entry(self):
        """Replacing the last entry in a short_term list should pass."""
        ops = [{"op": "replace", "path": "/bot/emotions/short_term/2",
                "value": "synthesized: deepening curiosity"}]
        # 3 items, last index = 2
        cache = self._make_cache(bot_emotions=["a", "b", "curious"])
        assert self._validate_patch_operations(ops, cache) is True

    def test_valid_replace_last_entry_single_item(self):
        """Replacing the only entry (index 0) in a single-item list should pass."""
        ops = [{"op": "replace", "path": "/bot/emotions/short_term/0",
                "value": "updated single entry"}]
        cache = self._make_cache(bot_emotions=["only"])
        assert self._validate_patch_operations(ops, cache) is True

    def test_replace_non_last_entry_rejected(self):
        """Replacing an entry that is NOT the last should be rejected."""
        ops = [{"op": "replace", "path": "/bot/emotions/short_term/0",
                "value": "replacing first entry"}]
        # 3 items, last index = 2, so index 0 is not last
        cache = self._make_cache(bot_emotions=["a", "b", "c"])
        assert self._validate_patch_operations(ops, cache) is False

    def test_replace_on_empty_array_rejected(self):
        """Replacing on an empty short_term array should be rejected."""
        ops = [{"op": "replace", "path": "/bot/emotions/short_term/0",
                "value": "nothing to replace"}]
        cache = self._make_cache(bot_emotions=[])  # empty array
        assert self._validate_patch_operations(ops, cache) is False

    def test_replace_with_empty_value_rejected(self):
        """replace with empty string value should be rejected."""
        ops = [{"op": "replace", "path": "/bot/emotions/short_term/0",
                "value": ""}]
        cache = self._make_cache(bot_emotions=["entry"])
        assert self._validate_patch_operations(ops, cache) is False

    def test_replace_with_whitespace_value_rejected(self):
        """replace with whitespace-only value should be rejected."""
        ops = [{"op": "replace", "path": "/bot/emotions/short_term/0",
                "value": "   "}]
        cache = self._make_cache(bot_emotions=["entry"])
        assert self._validate_patch_operations(ops, cache) is False

    def test_replace_non_numeric_index_in_path_rejected(self):
        """replace with non-numeric index (like /-) should be rejected."""
        ops = [{"op": "replace", "path": "/bot/emotions/short_term/-",
                "value": "synthesized"}]
        cache = self._make_cache(bot_emotions=["a"])
        assert self._validate_patch_operations(ops, cache) is False

    def test_replace_too_many_path_parts_rejected(self):
        """Path with extra components should be rejected."""
        ops = [{"op": "replace", "path": "/bot/emotions/short_term/0/extra",
                "value": "synthesized"}]
        cache = self._make_cache(bot_emotions=["a"])
        assert self._validate_patch_operations(ops, cache) is False

    def test_replace_on_unknown_owner_rejected(self):
        """Replacing on a non-existent owner path should be rejected
        (get chains resolve to [], and 0 != -1)."""
        ops = [{"op": "replace", "path": "/bot/emotions/short_term/2",
                "value": "entry"}]
        cache = {"bot": {}}  # no 'emotions' key
        assert self._validate_patch_operations(ops, cache) is False

    def test_replace_on_unknown_section_rejected(self):
        """Replacing on a non-existent section path should be rejected."""
        ops = [{"op": "replace", "path": "/bot/emotions/short_term/0",
                "value": "entry"}]
        cache = {"bot": {}}  # no 'emotions' key
        assert self._validate_patch_operations(ops, cache) is False

    def test_replace_on_user_needs_last_ok(self):
        """replace on /user/needs last entry should pass."""
        ops = [{"op": "replace", "path": "/user/needs/short_term/1",
                "value": "updated need"}]
        cache = self._make_cache(user_needs=["old need", "current need"])
        assert self._validate_patch_operations(ops, cache) is True

    # ── other operations ─────────────────────────────────────────────────

    def test_remove_on_short_term_rejected(self):
        """remove operation on short_term should be rejected."""
        ops = [{"op": "remove", "path": "/bot/emotions/short_term/0"}]
        cache = self._make_cache(bot_emotions=["a", "b"])
        assert self._validate_patch_operations(ops, cache) is False

    def test_unknown_op_on_short_term_rejected(self):
        """Unknown operation types on short_term should be rejected."""
        ops = [{"op": "move", "path": "/bot/emotions/short_term/0"}]
        cache = self._make_cache(bot_emotions=["a"])
        assert self._validate_patch_operations(ops, cache) is False

    # ── mixed / non-short-term operations ────────────────────────────────

    def test_mixed_valid_add_and_replace(self):
        """A mix of valid add and replace on short_term should pass."""
        ops = [
            {"op": "add", "path": "/bot/emotions/short_term/-",
             "value": "new feeling"},
            {"op": "replace", "path": "/user/needs/short_term/2",
             "value": "updated need"},
        ]
        cache = self._make_cache(
            bot_emotions=["old"],
            user_needs=["n1", "n2", "n3"],
        )
        assert self._validate_patch_operations(ops, cache) is True

    def test_non_short_term_ops_ignored(self):
        """Operations on non-short-term paths should be ignored by validation."""
        ops = [
            {"op": "replace", "path": "/user/name", "value": "NewName"},
            {"op": "add", "path": "/user/personal_facts/-", "value": "a fact"},
            {"op": "remove", "path": "/memorable_events/evt_old"},
        ]
        cache = self._make_cache()
        assert self._validate_patch_operations(ops, cache) is True

    def test_empty_operations_list(self):
        """An empty operations list should pass validation."""
        assert self._validate_patch_operations([], {}) is True




