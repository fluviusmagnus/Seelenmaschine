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
        # 2. Conversation start marker (system)
        # 3. Previous message (user)
        # 4. Conversation end marker (system)
        # 5. Related summaries (system)
        # 6. Related conversations (system)
        # 7. Current time (system)
        # 8. Current request (user)
        assert len(messages) == 8
        assert messages[0]["role"] == "system"
        assert "System prompt" in messages[0]["content"]
        assert messages[1]["role"] == "system"
        assert "BEGINNING OF THE CURRENT CONVERSATION" in messages[1]["content"]
        assert messages[2]["role"] == "user"
        assert messages[2]["content"] == "Previous message"
        assert messages[3]["role"] == "system"
        assert "END OF THE CURRENT CONVERSATION" in messages[3]["content"]
        assert messages[4]["role"] == "system"
        assert "Summary 1" in messages[4]["content"]
        assert messages[5]["role"] == "system"
        assert "Conversation 1" in messages[5]["content"]
        assert messages[6]["role"] == "system"
        assert "Current Time" in messages[6]["content"]
        assert messages[7]["role"] == "user"
        assert "Hello" in messages[7]["content"]

    @patch("llm.client.AsyncOpenAI")
    @patch(
        "llm.client.load_seele_json",
        return_value={"bot": {"name": "Seele"}, "user": {"name": "Alice"}},
    )
    @patch("llm.client.get_summary_prompt", return_value="summary prompt")
    def test_generate_summary(
        self, mock_get_prompt, mock_load_seele_json, mock_openai, llm_client
    ):
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
        mock_get_prompt.assert_called_once_with(
            None, "Alice: Message 1\nSeele: Response 1"
        )

    @patch("llm.client.AsyncOpenAI")
    @patch(
        "llm.client.load_seele_json",
        return_value={"bot": {"name": "Seele"}, "user": {"name": "Alice"}},
    )
    @patch("llm.client.get_memory_update_prompt", return_value="memory prompt")
    def test_generate_memory_update(
        self, mock_get_prompt, mock_load_seele_json, mock_openai, llm_client
    ):
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

        update = llm_client.generate_memory_update(messages, '{"bot": {}, "user": {}}')
        assert update == '{"patch": "value"}'
        mock_get_prompt.assert_called_once_with(
            "Alice: Message 1\nSeele: Response 1",
            '{"bot": {}, "user": {}}',
            None,
            None,
        )

    @patch("llm.client.AsyncOpenAI")
    @patch(
        "llm.client.load_seele_json",
        return_value={"bot": {"name": "Seele"}, "user": {"name": "Alice"}},
    )
    @patch(
        "llm.client.get_complete_memory_json_prompt",
        return_value="complete memory prompt",
    )
    def test_generate_complete_memory_json(
        self, mock_get_prompt, mock_load_seele_json, mock_openai, llm_client
    ):
        """Test generating complete memory json with display names."""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = '{"bot": {}, "user": {}}'

        mock_async_client = AsyncMock()
        mock_async_client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )
        mock_openai.return_value = mock_async_client

        messages = [
            {"role": "user", "text": "Message 1"},
            {"role": "assistant", "text": "Response 1"},
        ]

        result = llm_client.generate_complete_memory_json(
            messages,
            '{"bot": {}, "user": {}}',
            "patch failed",
        )

        assert result == '{"bot": {}, "user": {}}'
        mock_get_prompt.assert_called_once_with(
            "Alice: Message 1\nSeele: Response 1",
            '{"bot": {}, "user": {}}',
            "patch failed",
            None,
            None,
        )

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

    @pytest.mark.asyncio
    async def test_chat_async_replays_tool_calls_in_openai_format(self, llm_client):
        """Tool call results should be appended using OpenAI-compatible format."""
        llm_client._build_chat_messages = Mock(
            return_value=[{"role": "user", "content": "Hello"}]
        )
        llm_client._tool_executor = AsyncMock(return_value="tool output")
        llm_client._async_chat = AsyncMock(
            side_effect=[
                {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "name": "demo_tool",
                            "arguments": '{"q": "hi"}',
                        }
                    ],
                    "api_tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "demo_tool",
                                "arguments": '{"q": "hi"}',
                            },
                        }
                    ],
                    "reasoning_content": None,
                },
                {
                    "content": "final answer",
                    "tool_calls": None,
                    "api_tool_calls": None,
                    "reasoning_content": None,
                },
            ]
        )

        result = await llm_client.chat_async([], [], [])

        assert result == "final answer"
        second_call_messages = llm_client._async_chat.await_args_list[1].args[0]
        assistant_message = second_call_messages[-2]
        tool_message = second_call_messages[-1]

        assert assistant_message["role"] == "assistant"
        assert assistant_message["tool_calls"] == [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "demo_tool",
                    "arguments": '{"q": "hi"}',
                },
            }
        ]
        assert tool_message == {
            "tool_call_id": "call_1",
            "role": "tool",
            "content": "tool output",
        }

    @pytest.mark.asyncio
    async def test_chat_async_detailed_collects_intermediate_assistant_messages(
        self, llm_client
    ):
        """Tool-calling assistant text should be preserved as normal assistant messages."""
        llm_client._build_chat_messages = Mock(
            return_value=[{"role": "user", "content": "Hello"}]
        )
        llm_client._tool_executor = AsyncMock(return_value="tool output")
        llm_client._async_chat = AsyncMock(
            side_effect=[
                {
                    "content": "我先帮你查一下。",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "name": "demo_tool",
                            "arguments": '{"q": "hi"}',
                        }
                    ],
                    "api_tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "demo_tool",
                                "arguments": '{"q": "hi"}',
                            },
                        }
                    ],
                    "reasoning_content": None,
                },
                {
                    "content": "查到了，结果如下。",
                    "tool_calls": None,
                    "api_tool_calls": None,
                    "reasoning_content": None,
                },
            ]
        )

        result = await llm_client.chat_async_detailed([], [], [])

        assert result == {
            "final_text": "查到了，结果如下。",
            "assistant_messages": ["我先帮你查一下。", "查到了，结果如下。"],
        }

    @pytest.mark.asyncio
    @patch("llm.client.AsyncOpenAI")
    async def test_async_chat_extracts_api_tool_calls(self, mock_openai, llm_client):
        """_async_chat should keep both execution and API tool call formats."""
        mock_tool_call = Mock()
        mock_tool_call.id = "call_1"
        mock_tool_call.type = "function"
        mock_tool_call.function = Mock()
        mock_tool_call.function.name = "demo_tool"
        mock_tool_call.function.arguments = '{"q": "hi"}'

        mock_message = Mock()
        mock_message.content = None
        mock_message.tool_calls = [mock_tool_call]
        mock_message.reasoning_content = None

        mock_response = Mock()
        mock_response.choices = [Mock(message=mock_message)]

        mock_async_client = AsyncMock()
        mock_async_client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )
        mock_openai.return_value = mock_async_client

        llm_client._ensure_chat_client_initialized()
        result = await llm_client._async_chat(
            [{"role": "user", "content": "hello"}],
            use_tools=False,
            force_chat_model=True,
        )

        assert result["tool_calls"] == [
            {
                "id": "call_1",
                "name": "demo_tool",
                "arguments": '{"q": "hi"}',
            }
        ]
        assert result["api_tool_calls"] == [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "demo_tool",
                    "arguments": '{"q": "hi"}',
                },
            }
        ]

    @pytest.mark.asyncio
    @patch("llm.client.AsyncOpenAI")
    async def test_async_chat_includes_tools_in_same_request(
        self, mock_openai, llm_client
    ):
        """When tools are registered, they should be sent in the same chat request."""
        mock_message = Mock()
        mock_message.content = "ok"
        mock_message.tool_calls = None
        mock_message.reasoning_content = None

        mock_response = Mock()
        mock_response.choices = [Mock(message=mock_message)]

        mock_async_client = AsyncMock()
        mock_async_client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )
        mock_openai.return_value = mock_async_client

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "vision_tool",
                    "description": "Analyze an image",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        llm_client.set_tools(tools)

        result = await llm_client._async_chat(
            [{"role": "user", "content": "hello"}],
            use_tools=True,
            force_chat_model=True,
        )

        assert result["content"] == "ok"
        create_kwargs = mock_async_client.chat.completions.create.await_args.kwargs
        assert create_kwargs["tools"] == tools
        assert create_kwargs["messages"] == [{"role": "user", "content": "hello"}]
