import pytest
from unittest.mock import Mock, patch, AsyncMock

from llm.client import LLMClient


@pytest.fixture
def mock_config():
    """Mock configuration."""
    with patch("llm.client.Config") as mock:
        mock.DEBUG_SHOW_FULL_PROMPT = False
        mock.OPENAI_API_KEY = "test-key"
        mock.OPENAI_API_BASE = "https://api.test.com/v1"
        mock.CHAT_MODEL = "gpt-4"
        mock.TOOL_MODEL = "gpt-4"
        yield mock


@pytest.fixture
def llm_client(mock_config):
    """Create LLMClient with mocked config."""
    return LLMClient()


class TestLLMClient:
    """Test LLMClient functionality."""

    def test_initialization(self, llm_client):
        """Test LLM client initializes correctly."""
        assert llm_client.api_key == "test-key"
        assert llm_client.api_base == "https://api.test.com/v1"
        assert llm_client.chat_model == "gpt-4"
        assert llm_client.tool_model == "gpt-4"

    def test_set_tool_executor(self, llm_client):
        """Test setting tool executor."""
        executor = Mock()
        llm_client.set_tool_executor(executor)
        assert llm_client._tool_executor == executor

    def test_set_tools(self, llm_client):
        """Test setting tools."""
        tools = [
            {"type": "function", "function": {"name": "test", "description": "test"}},
        ]
        llm_client.set_tools(tools)
        assert llm_client._tools_cache == tools

    @patch("llm.client.get_cacheable_system_prompt", return_value="System prompt")
    @patch("llm.client.get_current_time_str", return_value="2026-01-28 12:00:00")
    def test_build_chat_messages(self, mock_time, mock_system_prompt, llm_client):
        """Test building chat messages."""
        current_context = [
            {"role": "user", "content": "Previous message"},
            {"role": "user", "content": "Hello"},
        ]
        retrieved_summaries = ["Summary 1"]
        retrieved_conversations = ["Conversation 1"]

        messages = llm_client._build_chat_messages(
            current_context, retrieved_summaries, retrieved_conversations
        )

        # Expected structure:
        # 1. System prompt
        # 2. Previous message (user)
        # 3. Related summaries (system)
        # 4. Related conversations (system)
        # 5. Current time (system)
        # 6. Current request (user)
        assert len(messages) == 6
        assert messages[0]["role"] == "system"
        assert "System prompt" in messages[0]["content"]
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "Previous message"
        assert messages[2]["role"] == "system"
        assert "Summary 1" in messages[2]["content"]
        assert messages[3]["role"] == "system"
        assert "Conversation 1" in messages[3]["content"]
        assert messages[4]["role"] == "system"
        assert "Current Time" in messages[4]["content"]
        assert messages[5]["role"] == "user"
        assert "Hello" in messages[5]["content"]

    @patch("llm.client.AsyncOpenAI")
    def test_generate_summary(self, mock_openai, llm_client):
        """Test generating summary."""
        # Setup mock response
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "Summary result"

        # Setup mock client
        mock_async_client = AsyncMock()
        mock_async_client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )
        mock_openai.return_value = mock_async_client

        new_conversations = [
            {"role": "user", "text": "Message 1"},
            {"role": "assistant", "text": "Response 1"},
        ]

        summary = llm_client.generate_summary(None, new_conversations)
        assert summary == "Summary result"

    @patch("llm.client.AsyncOpenAI")
    def test_generate_memory_update(self, mock_openai, llm_client):
        """Test generating memory update."""
        # Setup mock response
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = '{"patch": "value"}'

        # Setup mock client
        mock_async_client = AsyncMock()
        mock_async_client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )
        mock_openai.return_value = mock_async_client

        messages = [
            {"role": "user", "text": "Message 1"},
            {"role": "assistant", "text": "Response 1"},
        ]

        update = llm_client.generate_memory_update(messages)
        assert update == '{"patch": "value"}'

    @patch("llm.client.AsyncOpenAI")
    def test_close(self, mock_openai, llm_client):
        """Test closing client."""
        mock_async_client = AsyncMock()
        mock_openai.return_value = mock_async_client

        # Initialize clients
        llm_client._ensure_chat_client_initialized()
        llm_client._ensure_tool_client_initialized()

        llm_client.close()

        # Verify clients were closed
        assert mock_async_client.close.called
