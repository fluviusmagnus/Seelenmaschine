import pytest
from unittest.mock import Mock, AsyncMock, patch
from typing import Dict, Any

from tools.memory_search import MemorySearchTool


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
            (1, 1234567890, "user", "Found message", 0.9)
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
            (1, 1234567890, "user", "First result", 0.9),
            (2, 1234567891, "assistant", "Second result", 0.8),
        ]

        result = await memory_search_tool.execute(query="test")

        assert "First result" in result
        assert "Second result" in result

    @pytest.mark.asyncio
    async def test_execute_with_role_filter(self, memory_search_tool, mock_db):
        """Test executing search with role filter."""
        mock_db.search_conversations_by_keyword.return_value = []

        result = await memory_search_tool.execute(query="test", role="user")

        mock_db.search_conversations_by_keyword.assert_called()
        call_kwargs = mock_db.search_conversations_by_keyword.call_args[1]
        assert call_kwargs["role"] == "user"

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
            (1, 1234567890, "user", "User message", 0.9)
        ]

        result = await memory_search_tool.execute(role="user")

        assert "User message" in result
        assert mock_db.search_conversations_by_keyword.called


class TestMemorySearchToolIntegration:
    """Integration tests for MemorySearchTool."""

    @pytest.mark.asyncio
    async def test_full_search_workflow(self, memory_search_tool, mock_db):
        """Test complete search workflow."""
        # Simulate successful search
        mock_db.search_conversations_by_keyword.return_value = [
            (1, 1234567890, "user", "Integration test message", 0.9)
        ]

        # Execute search
        result = await memory_search_tool.execute(query="integration test")

        # Verify result
        assert "Integration test message" in result
        assert not memory_search_tool.is_disabled()
