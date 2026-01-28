import pytest
import tempfile
import json
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock, MagicMock

from tools.mcp_client import MCPClient


@pytest.fixture
def temp_config_dir(tmp_path):
    """Create temporary directory for MCP config."""
    return tmp_path


@pytest.fixture
def mcp_config_file(temp_config_dir):
    """Create a test MCP config file."""
    config_data = {
        "mcpServers": {
            "test-server": {
                "command": "test-cmd",
                "args": ["arg1", "arg2"],
                "bearerToken": "test-token-123",
            },
            "server-without-token": {"command": "another-cmd"},
        }
    }
    config_path = temp_config_dir / "mcp_servers.json"
    with open(config_path, "w") as f:
        json.dump(config_data, f)
    return config_path


@pytest.fixture
def mcp_client(mcp_config_file):
    """Create MCPClient with test config."""
    return MCPClient(config_path=mcp_config_file)


class TestMCPClient:
    """Test MCPClient functionality."""

    def test_initialization(self, mcp_config_file):
        """Test client initialization."""
        client = MCPClient(config_path=mcp_config_file)
        assert client.config_path == mcp_config_file
        assert client.client is None
        assert client._tools_cache is None
        assert "mcpServers" in client._config

    def test_initialization_nonexistent_config(self, tmp_path):
        """Test initialization with nonexistent config file."""
        nonexistent_path = tmp_path / "nonexistent.json"
        client = MCPClient(config_path=nonexistent_path)
        assert client._config == {"mcpServers": {}}

    def test_get_default_roots(self, mcp_client):
        """Test getting default roots."""
        roots = mcp_client._get_default_roots()
        assert isinstance(roots, list)
        assert len(roots) > 0
        assert roots[0].startswith("file://")

    def test_load_config_valid(self, mcp_config_file):
        """Test loading valid config."""
        client = MCPClient(config_path=mcp_config_file)
        config = client._load_config()
        assert "mcpServers" in config
        assert "test-server" in config["mcpServers"]

    def test_load_config_invalid_json(self, temp_config_dir):
        """Test loading invalid JSON config."""
        config_path = temp_config_dir / "invalid.json"
        with open(config_path, "w") as f:
            f.write("not valid json")

        client = MCPClient(config_path=config_path)
        config = client._load_config()
        assert config == {"mcpServers": {}}

    def test_process_config_with_bearer_token(self, mcp_client):
        """Test processing config with bearer token conversion."""
        raw_config = {
            "mcpServers": {"test": {"command": "cmd", "bearerToken": "token123"}}
        }

        processed = mcp_client._process_config(raw_config)

        assert "test" in processed["mcpServers"]
        assert "bearerToken" not in processed["mcpServers"]["test"]
        assert "headers" in processed["mcpServers"]["test"]
        assert (
            processed["mcpServers"]["test"]["headers"]["Authorization"]
            == "Bearer token123"
        )

    def test_process_config_without_bearer_token(self, mcp_client):
        """Test processing config without bearer token."""
        raw_config = {"mcpServers": {"test": {"command": "cmd"}}}

        processed = mcp_client._process_config(raw_config)

        assert "test" in processed["mcpServers"]
        assert "command" in processed["mcpServers"]["test"]
        assert "headers" not in processed["mcpServers"]["test"]

    @pytest.mark.asyncio
    async def test_aenter_no_servers_configured(self, tmp_path):
        """Test async enter with no servers configured."""
        config_path = tmp_path / "empty.json"
        with open(config_path, "w") as f:
            json.dump({"mcpServers": {}}, f)

        client = MCPClient(config_path=config_path)
        result = await client.__aenter__()

        assert result is client
        assert client.client is None

    @pytest.mark.asyncio
    async def test_aexit_no_client(self, mcp_client):
        """Test async exit when no client."""
        await mcp_client.__aexit__(None, None, None)

    @pytest.mark.asyncio
    async def test_list_tools_no_client(self, mcp_client):
        """Test listing tools when client is not connected."""
        tools = await mcp_client.list_tools()
        assert tools == []

    @pytest.mark.asyncio
    async def test_list_tools_success(self, mcp_client):
        """Test listing tools successfully."""
        # Create a proper mock client that returns a mock response
        mock_client = Mock()

        # Create mock tools
        mock_tool1 = Mock()
        mock_tool1.name = "tool1"
        mock_tool1.description = "Test tool 1"
        mock_tool1.inputSchema = {"type": "object"}

        mock_tool2 = Mock()
        mock_tool2.name = "tool2"
        mock_tool2.description = "Test tool 2"
        mock_tool2.inputSchema = {"type": "string"}

        # Create mock response with both result and tools attributes
        # to match fastmcp.Client.list_tools() response format
        mock_result = Mock()
        mock_result.tools = [mock_tool1, mock_tool2]

        mock_tools_response = Mock()
        mock_tools_response.result = mock_result

        # Set up the mock
        mock_client.list_tools = AsyncMock(return_value=mock_tools_response)
        mcp_client.client = mock_client

        tools = await mcp_client.list_tools()

        assert len(tools) == 2
        assert tools[0]["type"] == "function"
        assert tools[0]["function"]["name"] == "tool1"
        assert tools[1]["function"]["name"] == "tool2"

    @pytest.mark.asyncio
    async def test_list_tools_dict_format(self, mcp_client):
        """Test listing tools with dict response format."""
        mock_client = AsyncMock()

        mock_response = {
            "result": {
                "tools": [
                    {"name": "dict_tool", "description": "Dict tool", "inputSchema": {}}
                ]
            }
        }

        mock_client.list_tools = AsyncMock(return_value=mock_response)
        mcp_client.client = mock_client

        tools = await mcp_client.list_tools()

        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "dict_tool"

    @pytest.mark.asyncio
    async def test_list_tools_error_handling(self, mcp_client):
        """Test list_tools error handling."""
        mock_client = AsyncMock()
        mock_client.list_tools = AsyncMock(side_effect=Exception("API Error"))
        mcp_client.client = mock_client

        tools = await mcp_client.list_tools()

        assert tools == []

    def test_get_tools_sync_with_cache(self, mcp_client):
        """Test get_tools_sync returns cached tools."""
        cached_tools = [{"type": "function", "function": {"name": "cached"}}]
        mcp_client._tools_cache = cached_tools

        tools = mcp_client.get_tools_sync()

        assert tools == cached_tools

    @pytest.mark.asyncio
    async def test_call_tool_no_client(self, mcp_client):
        """Test calling tool when client is not connected."""
        result = await mcp_client.call_tool("test_tool", {"arg": "value"})
        assert "not connected" in result

    @pytest.mark.asyncio
    async def test_call_tool_success(self, mcp_client):
        """Test calling tool successfully."""
        mock_client = AsyncMock()

        mock_result = Mock()
        mock_content = Mock()
        mock_content.text = "Tool result text"
        mock_result.content = [mock_content]

        mock_client.call_tool = AsyncMock(return_value=mock_result)
        mcp_client.client = mock_client

        result = await mcp_client.call_tool("test_tool", {"arg": "value"})

        assert result == "Tool result text"
        mock_client.call_tool.assert_awaited_once_with("test_tool", {"arg": "value"})

    @pytest.mark.asyncio
    async def test_call_tool_no_content(self, mcp_client):
        """Test calling tool when result has no content."""
        mock_client = AsyncMock()

        mock_result = Mock()
        mock_result.content = []

        mock_client.call_tool = AsyncMock(return_value=mock_result)
        mcp_client.client = mock_client

        result = await mcp_client.call_tool("test_tool", {})

        assert "no content" in result

    @pytest.mark.asyncio
    async def test_call_tool_error_handling(self, mcp_client):
        """Test call_toolkit error handling."""
        from unittest.mock import patch

        # Mock the logger to prevent loguru formatting error
        with patch("tools.mcp_client.logger") as mock_logger:
            mock_client = AsyncMock()
            mock_client.call_tool = AsyncMock(side_effect=Exception("Tool Error"))
            mcp_client.client = mock_client

            result = await mcp_client.call_tool("test_tool", {})

            assert "failed" in result

    @pytest.mark.asyncio
    async def test_async_context_manager(self, mcp_client):
        """Test async context manager usage."""
        with patch("tools.mcp_client.Client") as mock_client_class:
            mock_instance = AsyncMock()
            mock_client_class.return_value = mock_instance

            async with mcp_client as client:
                assert client is mcp_client

            mock_instance.__aenter__.assert_awaited_once()
            mock_instance.__aexit__.assert_awaited_once()
