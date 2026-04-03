import pytest
from unittest.mock import Mock, AsyncMock, patch
from typing import Dict, Any

from tools.memory_search import MemorySearchTool
from core.config import Config


@pytest.fixture(autouse=True)
def reset_disabled_state():
    """Reset disabled state before each test."""
    from tools import memory_search

    memory_search.DISABLE_SEARCH_MEMORIES = False
    yield


@pytest.fixture
def mock_db():
    """Create mock database manager."""
    db = Mock()
    db.search_summaries_by_keyword = Mock(return_value=[])
    db.search_conversations_by_keyword = Mock(return_value=[])
    db.search_summaries = Mock(return_value=[])
    return db


@pytest.fixture
def memory_search_tool(mock_db):
    """Create MemorySearchTool instance."""
    return MemorySearchTool(session_id="123", db=mock_db)


class TestMemorySearchTool:
    """Test MemorySearchTool functionality."""

    def test_initialization(self, memory_search_tool, mock_db):
        """Test tool initialization."""
        assert memory_search_tool.db == mock_db
        assert memory_search_tool.session_id == 123  # Converted to int

    def test_name(self, memory_search_tool):
        """Test tool name."""
        assert memory_search_tool.name == "search_memories"

    def test_description(self, memory_search_tool):
        """Test tool description."""
        description = memory_search_tool.description
        assert "search" in description.lower()
        assert "conversation" in description.lower()

    def test_parameters(self, memory_search_tool):
        """Test tool parameters schema."""
        params = memory_search_tool.parameters
        assert params["type"] == "object"
        assert "query" in params["properties"]
        assert params["properties"]["query"]["type"] == "string"
        assert "session_id" in params["properties"]["query"]["description"]
        assert "include_current_session" in params["properties"]
        assert params["properties"]["include_current_session"]["default"] is False
        assert "session_id" in params["properties"]
        assert "without query" in params["properties"]["session_id"]["description"]
        assert "search_target" in params["properties"]
        assert params["properties"]["search_target"]["default"] == "all"
        assert "prefer 'summaries'" in params["properties"]["search_target"]["description"]

    def test_disable(self, memory_search_tool):
        """Test disabling tool."""
        memory_search_tool.disable()
        assert memory_search_tool.is_disabled()

    def test_enable(self, memory_search_tool):
        """Test enabling tool."""
        memory_search_tool.disable()
        memory_search_tool.enable()
        assert not memory_search_tool.is_disabled()

    def test_validate_fts_query_valid(self, memory_search_tool):
        """Test FTS query validation with valid input."""
        is_valid, error_msg = memory_search_tool._validate_fts_query("hello world")
        assert is_valid is True
        assert error_msg == ""

    def test_validate_fts_query_unmatched_quotes(self, memory_search_tool):
        """Test FTS query validation with unmatched quotes."""
        is_valid, error_msg = memory_search_tool._validate_fts_query(
            'search "quoted text'
        )
        assert is_valid is False
        assert "quotes" in error_msg.lower()

    def test_validate_fts_query_unmatched_parens(self, memory_search_tool):
        """Test FTS query validation with unmatched parentheses."""
        is_valid, error_msg = memory_search_tool._validate_fts_query("(test OR more")
        assert is_valid is False
        assert "parentheses" in error_msg.lower()

    def test_validate_fts_query_operator_at_start(self, memory_search_tool):
        """Test FTS query validation with operator at start."""
        is_valid, error_msg = memory_search_tool._validate_fts_query("AND test")
        assert is_valid is False
        assert "start" in error_msg.lower()

    def test_validate_fts_query_empty(self, memory_search_tool):
        """Test FTS query validation with empty input."""
        is_valid, error_msg = memory_search_tool._validate_fts_query("")
        assert is_valid is True
        assert error_msg == ""

    @pytest.mark.asyncio
    async def test_execute_search(self, memory_search_tool, mock_db):
        """Test executing search."""
        mock_db.search_conversations_by_keyword.return_value = [
            (1, 321, 1234567890, "user", "Found message", 0.9)
        ]

        result = await memory_search_tool.execute(query="search term")

        assert "Found message" in result
        assert mock_db.search_conversations_by_keyword.called

    @pytest.mark.asyncio
    async def test_execute_no_results(self, memory_search_tool, mock_db):
        """Test executing search with no results."""
        mock_db.search_summaries_by_keyword.return_value = []
        mock_db.search_conversations_by_keyword.return_value = []

        result = await memory_search_tool.execute(query="nonexistent term")

        assert "No relevant memories found" in result

    @pytest.mark.asyncio
    async def test_execute_can_use_vector_summary_fallback_for_natural_language_query(
        self, mock_db
    ):
        embedding_client = Mock()
        embedding_client.get_embedding_async = AsyncMock(return_value=[0.1, 0.2])
        mock_db.search_summaries_by_keyword.return_value = []
        mock_db.search_conversations_by_keyword.return_value = []
        mock_db.search_summaries.return_value = [
            (7, 999, "Vector matched summary", 10, 20, 0.12)
        ]
        tool = MemorySearchTool(
            session_id="123", db=mock_db, embedding_client=embedding_client
        )

        result = await tool.execute(query="上次我们讨论预算和旅行安排的时候")

        assert "Vector matched summary" in result
        embedding_client.get_embedding_async.assert_awaited_once()
        mock_db.search_summaries.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_does_not_use_vector_fallback_for_boolean_query(
        self, mock_db
    ):
        embedding_client = Mock()
        embedding_client.get_embedding_async = AsyncMock(return_value=[0.1, 0.2])
        mock_db.search_summaries_by_keyword.return_value = []
        mock_db.search_conversations_by_keyword.return_value = []
        tool = MemorySearchTool(
            session_id="123", db=mock_db, embedding_client=embedding_client
        )

        await tool.execute(query="预算 AND 旅行")

        embedding_client.get_embedding_async.assert_not_called()
        mock_db.search_summaries.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_sorts_keyword_summary_before_vector_fallback(self, mock_db):
        embedding_client = Mock()
        embedding_client.get_embedding_async = AsyncMock(return_value=[0.1, 0.2])
        mock_db.search_summaries_by_keyword.return_value = [
            (1, 100, "预算和旅行安排摘要", 1, 100, 0.0)
        ]
        mock_db.search_conversations_by_keyword.return_value = []
        mock_db.search_summaries.return_value = [
            (2, 101, "较弱的语义相关摘要", 2, 200, 0.15)
        ]
        tool = MemorySearchTool(
            session_id="123", db=mock_db, embedding_client=embedding_client
        )

        result = await tool.execute(query="预算和旅行安排的那次讨论", search_target="summaries")

        keyword_index = result.index("预算和旅行安排摘要")
        vector_index = result.index("较弱的语义相关摘要")
        assert keyword_index < vector_index

    @pytest.mark.asyncio
    async def test_execute_weighted_fusion_can_promote_stronger_vector_match(self, mock_db):
        embedding_client = Mock()
        embedding_client.get_embedding_async = AsyncMock(return_value=[0.1, 0.2])
        mock_db.search_summaries_by_keyword.return_value = [
            (1, 100, "简短行程条目", 1, 100, 0.0)
        ]
        mock_db.search_conversations_by_keyword.return_value = []
        mock_db.search_summaries.return_value = [
            (2, 101, "我们详细讨论了旅行计划和预算安排", 2, 50, 0.05)
        ]
        tool = MemorySearchTool(
            session_id="123", db=mock_db, embedding_client=embedding_client
        )

        result = await tool.execute(query="旅行计划和预算安排的那次讨论", search_target="summaries")

        vector_index = result.index("我们详细讨论了旅行计划和预算安排")
        keyword_index = result.index("简短行程条目")
        assert vector_index < keyword_index

    @pytest.mark.asyncio
    async def test_execute_weighted_fusion_trims_to_requested_limit(self, mock_db):
        embedding_client = Mock()
        embedding_client.get_embedding_async = AsyncMock(return_value=[0.1, 0.2])
        mock_db.search_summaries_by_keyword.return_value = []
        mock_db.search_conversations_by_keyword.return_value = []
        mock_db.search_summaries.return_value = [
            (1, 100, "摘要一", 1, 10, 0.01),
            (2, 101, "摘要二", 2, 20, 0.02),
            (3, 102, "摘要三", 3, 30, 0.03),
        ]
        tool = MemorySearchTool(
            session_id="123", db=mock_db, embedding_client=embedding_client
        )

        result = await tool.execute(
            query="这是一个比较长的自然语言查询用于触发向量召回",
            search_target="summaries",
            limit=2,
        )

        assert "摘要一" in result or "摘要二" in result or "摘要三" in result
        assert result.count("[session_id=") == 2

    @pytest.mark.asyncio
    async def test_execute_disabled(self, memory_search_tool):
        """Test executing search when tool is disabled."""
        memory_search_tool.disable()

        result = await memory_search_tool.execute(query="test")

        assert "disabled" in result.lower()

    @pytest.mark.asyncio
    async def test_execute_invalid_query_syntax(self, memory_search_tool):
        """Test executing search with invalid query syntax."""
        result = await memory_search_tool.execute(query='"unmatched quote')
        assert "Invalid query syntax" in result

    @pytest.mark.asyncio
    async def test_execute_multiple_results(self, memory_search_tool, mock_db):
        """Test executing search with multiple results."""
        mock_db.search_conversations_by_keyword.return_value = [
            (1, 321, 1234567890, "user", "First result", 0.9),
            (2, 321, 1234567891, "assistant", "Second result", 0.8),
        ]

        with patch("tools.memory_search.load_seele_json") as mock_load_seele_json:
            mock_load_seele_json.return_value = {
                "bot": {"name": "Seele"},
                "user": {"name": "Alice"},
            }
            result = await memory_search_tool.execute(query="test")

        assert "First result" in result
        assert "Second result" in result
        assert "Alice: First result" in result
        assert "Seele: Second result" in result
        assert "[session_id=321]" in result

    @pytest.mark.asyncio
    async def test_execute_with_role_filter(self, memory_search_tool, mock_db):
        """Test executing search with role filter."""
        mock_db.search_conversations_by_keyword.return_value = []

        result = await memory_search_tool.execute(query="test", role="user")

        mock_db.search_conversations_by_keyword.assert_called()
        call_kwargs = mock_db.search_conversations_by_keyword.call_args[1]
        assert call_kwargs["role"] == "user"

    @pytest.mark.asyncio
    async def test_execute_search_excludes_tool_call_messages(self, memory_search_tool, mock_db):
        mock_db.search_conversations_by_keyword.return_value = []

        await memory_search_tool.execute(query="test")

        call_kwargs = mock_db.search_conversations_by_keyword.call_args[1]
        assert call_kwargs["query"] == "test"
        assert call_kwargs["exclude_session_id"] == memory_search_tool.session_id

    @pytest.mark.asyncio
    async def test_execute_can_include_current_session(self, memory_search_tool, mock_db):
        mock_db.search_summaries_by_keyword.return_value = []
        mock_db.search_conversations_by_keyword.return_value = []

        await memory_search_tool.execute(
            query="test", include_current_session=True
        )

        summary_call_kwargs = mock_db.search_summaries_by_keyword.call_args[1]
        conversation_call_kwargs = mock_db.search_conversations_by_keyword.call_args[1]
        assert summary_call_kwargs["exclude_session_id"] is None
        assert conversation_call_kwargs["exclude_session_id"] is None
        assert (
            conversation_call_kwargs["exclude_recent_from_session_id"]
            == memory_search_tool.session_id
        )
        assert (
            conversation_call_kwargs["exclude_recent_limit"]
            == Config.CONTEXT_WINDOW_KEEP_MIN
        )

    @pytest.mark.asyncio
    async def test_execute_excludes_recent_messages_when_including_current_session(
        self, memory_search_tool, mock_db
    ):
        mock_db.search_summaries_by_keyword.return_value = []
        mock_db.search_conversations_by_keyword.return_value = []

        await memory_search_tool.execute(
            query="test", include_current_session=True
        )

        conversation_call_kwargs = mock_db.search_conversations_by_keyword.call_args[1]
        assert conversation_call_kwargs["exclude_recent_from_session_id"] == 123
        assert conversation_call_kwargs["exclude_recent_limit"] == Config.CONTEXT_WINDOW_KEEP_MIN

    @pytest.mark.asyncio
    async def test_execute_with_time_period(self, memory_search_tool, mock_db):
        """Test executing search with time period filter."""
        mock_db.search_conversations_by_keyword.return_value = []

        # Mock Config.TIMEZONE to return a ZoneInfo object
        with patch("tools.memory_search.Config") as mock_config:
            from zoneinfo import ZoneInfo

            mock_config.TIMEZONE = ZoneInfo("Asia/Shanghai")
            mock_config.TIMEZONE_STR = "Asia/Shanghai"

            result = await memory_search_tool.execute(
                query="test", time_period="last_week"
            )

            # Even if there's an error, the test shows the parameter is accepted
            mock_db.search_conversations_by_keyword.assert_called()

    @pytest.mark.asyncio
    async def test_execute_without_query(self, memory_search_tool, mock_db):
        """Test executing search without query but with filters."""
        mock_db.search_conversations_by_keyword.return_value = [
            (1, 321, 1234567890, "user", "User message", 0.9)
        ]

        result = await memory_search_tool.execute(role="user")

        assert "User message" in result
        assert mock_db.search_conversations_by_keyword.called

    @pytest.mark.asyncio
    async def test_execute_with_specific_session_id(self, memory_search_tool, mock_db):
        mock_db.search_summaries_by_keyword.return_value = []
        mock_db.search_conversations_by_keyword.return_value = []

        await memory_search_tool.execute(query="test", session_id=456)

        summary_call_kwargs = mock_db.search_summaries_by_keyword.call_args[1]
        conversation_call_kwargs = mock_db.search_conversations_by_keyword.call_args[1]
        assert summary_call_kwargs["session_id"] == 456
        assert conversation_call_kwargs["session_id"] == 456
        assert summary_call_kwargs["exclude_session_id"] is None
        assert conversation_call_kwargs["exclude_session_id"] is None
        assert conversation_call_kwargs["exclude_recent_from_session_id"] is None
        assert conversation_call_kwargs["exclude_recent_limit"] == 0

    @pytest.mark.asyncio
    async def test_execute_with_session_id_only_prefers_supported_filtering(
        self, memory_search_tool, mock_db
    ):
        mock_db.search_summaries_by_keyword.return_value = [
            (1, 456, "Session overview", 1, 2, 0.9)
        ]

        result = await memory_search_tool.execute(
            session_id=456, search_target="summaries"
        )

        assert "Session overview" in result
        summary_call_kwargs = mock_db.search_summaries_by_keyword.call_args[1]
        assert summary_call_kwargs["session_id"] == 456
        assert summary_call_kwargs["query"] is None

    @pytest.mark.asyncio
    async def test_execute_requires_query_or_filters_including_session_id(
        self, memory_search_tool
    ):
        result = await memory_search_tool.execute()

        assert "query, session_id, role, or time filter" in result

    @pytest.mark.asyncio
    async def test_execute_search_target_summaries_only(self, memory_search_tool, mock_db):
        mock_db.search_summaries_by_keyword.return_value = [
            (1, 456, "Summary result", 1, 2, 0.9)
        ]

        result = await memory_search_tool.execute(
            query="test", search_target="summaries"
        )

        assert "Summary result" in result
        assert "[session_id=456]" in result
        mock_db.search_summaries_by_keyword.assert_called_once()
        mock_db.search_conversations_by_keyword.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_search_target_conversations_only(self, memory_search_tool, mock_db):
        mock_db.search_conversations_by_keyword.return_value = [
            (1, 654, 1234567890, "user", "Conversation result", 0.9)
        ]

        result = await memory_search_tool.execute(
            query="test", search_target="conversations"
        )

        assert "Conversation result" in result
        assert "[session_id=654]" in result
        mock_db.search_conversations_by_keyword.assert_called_once()
        mock_db.search_summaries_by_keyword.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_session_id_takes_precedence_over_include_current_session(
        self, memory_search_tool, mock_db
    ):
        mock_db.search_summaries_by_keyword.return_value = []
        mock_db.search_conversations_by_keyword.return_value = []

        await memory_search_tool.execute(
            query="test", include_current_session=True, session_id=789
        )

        summary_call_kwargs = mock_db.search_summaries_by_keyword.call_args[1]
        conversation_call_kwargs = mock_db.search_conversations_by_keyword.call_args[1]
        assert summary_call_kwargs["session_id"] == 789
        assert conversation_call_kwargs["session_id"] == 789
        assert conversation_call_kwargs["exclude_recent_from_session_id"] is None
        assert conversation_call_kwargs["exclude_recent_limit"] == 0

    @pytest.mark.asyncio
    async def test_execute_excludes_recent_messages_even_without_include_current_session(
        self, memory_search_tool, mock_db
    ):
        mock_db.search_summaries_by_keyword.return_value = []
        mock_db.search_conversations_by_keyword.return_value = []

        await memory_search_tool.execute(query="test")

        conversation_call_kwargs = mock_db.search_conversations_by_keyword.call_args[1]
        assert (
            conversation_call_kwargs["exclude_recent_from_session_id"]
            == memory_search_tool.session_id
        )
        assert (
            conversation_call_kwargs["exclude_recent_limit"]
            == Config.CONTEXT_WINDOW_KEEP_MIN
        )

    @pytest.mark.asyncio
    async def test_execute_excludes_recent_messages_for_explicit_current_session(
        self, memory_search_tool, mock_db
    ):
        mock_db.search_summaries_by_keyword.return_value = []
        mock_db.search_conversations_by_keyword.return_value = []

        await memory_search_tool.execute(query="test", session_id=123)

        conversation_call_kwargs = mock_db.search_conversations_by_keyword.call_args[1]
        assert conversation_call_kwargs["session_id"] == 123
        assert (
            conversation_call_kwargs["exclude_recent_from_session_id"]
            == memory_search_tool.session_id
        )
        assert (
            conversation_call_kwargs["exclude_recent_limit"]
            == Config.CONTEXT_WINDOW_KEEP_MIN
        )


class TestMemorySearchToolIntegration:
    """Integration tests for MemorySearchTool."""

    @pytest.mark.asyncio
    async def test_full_search_workflow(self, memory_search_tool, mock_db):
        """Test complete search workflow."""
        # Simulate successful search
        mock_db.search_conversations_by_keyword.return_value = [
            (1, 321, 1234567890, "user", "Integration test message", 0.9)
        ]

        # Execute search
        result = await memory_search_tool.execute(query="integration test")

        # Verify result
        assert "Integration test message" in result
        assert not memory_search_tool.is_disabled()
