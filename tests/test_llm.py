import pytest
from unittest.mock import Mock, patch, AsyncMock

from llm.client import LLMClient


@pytest.fixture
def mock_config():
    """Mock configuration."""
    with patch('llm.client.Config') as mock:
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
            {"type": "function", "function": {"name": "test", "description": "test"}}
        ]
        llm_client.set_tools(tools)
        assert llm_client._tools_cache == tools

    def test_build_chat_messages(self, llm_client):
        """Test building chat messages."""
        with patch('llm.client.get_system_prompt', return_value="System prompt"):
            # current_context should include the current user message
            # (in real usage, it's added to memory before calling this)
            current_context = [
                {"role": "user", "content": "Previous message"},
                {"role": "user", "content": "Hello"}
            ]
            retrieved_summaries = ["Summary 1"]
            retrieved_conversations = ["Conversation 1"]

            messages = llm_client._build_chat_messages(
                current_context,
                retrieved_summaries,
                retrieved_conversations
            )

            # Expected structure:
            # 1. System prompt
            # 2. Related summaries (system)
            # 3. Related conversations (system)
            # 4. Previous message (user)
            # 5. Current message (user)
            assert len(messages) == 5
            assert messages[0]["role"] == "system"
            assert messages[0]["content"] == "System prompt"
            assert messages[1]["role"] == "system"
            assert "Summary 1" in messages[1]["content"]
            assert messages[2]["role"] == "system"
            assert "Conversation 1" in messages[2]["content"]
            assert messages[3]["role"] == "user"
            assert messages[3]["content"] == "Previous message"
            assert messages[4]["role"] == "user"
            assert messages[4]["content"] == "Hello"

    @patch('llm.client.get_system_prompt', return_value="System prompt")
    @patch('llm.client.get_summary_prompt', return_value="Summarize this")
    def test_generate_summary(self, mock_summary_prompt, mock_system_prompt, llm_client):
        """Test generating summary."""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "Summary result"

        with patch.object(llm_client, '_ensure_chat_client_initialized'):
            llm_client._chat_client = AsyncMock()
            llm_client._chat_client.chat.completions.create = AsyncMock(return_value=mock_response)

            new_conversations = [
                {"role": "user", "text": "Message 1"},
                {"role": "assistant", "text": "Response 1"}
            ]

            summary = llm_client.generate_summary(None, new_conversations)
            assert summary == "Summary result"

    @patch('llm.client.get_system_prompt', return_value="System prompt")
    @patch('llm.client.get_memory_update_prompt', return_value="Generate JSON patch")
    def test_generate_memory_update(self, mock_memory_prompt, mock_system_prompt, llm_client):
        """Test generating memory update."""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = '{"patch": "value"}'

        with patch.object(llm_client, '_ensure_chat_client_initialized'):
            llm_client._chat_client = AsyncMock()
            llm_client._chat_client.chat.completions.create = AsyncMock(return_value=mock_response)

            messages = [
                {"role": "user", "text": "Message 1"},
                {"role": "assistant", "text": "Response 1"}
            ]

            update = llm_client.generate_memory_update(messages)
            assert update == '{"patch": "value"}'

    def test_close(self, llm_client):
        """Test closing client."""
        with patch.object(llm_client, '_async_close', new_callable=AsyncMock) as mock_close:
            llm_client.close()
            assert mock_close.called
