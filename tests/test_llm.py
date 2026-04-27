import pytest
import base64
from unittest.mock import Mock, patch, AsyncMock

from core.file_service import FileArtifactService
from llm.chat_client import LLMClient
from llm.request_executor import ChatRequestExecutor
from llm.tool_loop import ToolLoop


@pytest.fixture
def mock_config():
    """Mock configuration."""
    with patch("llm.chat_client.Config") as mock:
        mock.DEBUG_SHOW_FULL_PROMPT = False
        mock.OPENAI_API_KEY = "test-key"
        mock.OPENAI_API_BASE = "https://api.test.com/v1"
        mock.CHAT_MODEL = "gpt-4"
        mock.TOOL_MODEL = "gpt-4"
        mock.TOOL_LLM_MAX_RESPONSE_CHARS = 12000
        mock.TOOL_LLM_TRUNCATE_HEAD_CHARS = 6000
        mock.TOOL_LLM_TRUNCATE_TAIL_CHARS = 4000
        mock.TOOL_LOOP_MAX_ITERATIONS = 8
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

    def test_sanitize_tool_response_for_prompt_omits_large_base64(self, llm_client):
        """Binary-looking tool payloads should not be appended to prompt verbatim."""
        base64_payload = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo+/=" * 64
        response = f"prefix {base64_payload} suffix"

        sanitized = llm_client._sanitize_tool_response_for_prompt(response)

        assert sanitized.startswith("[tool output omitted: detected large base64")
        assert "A" * 100 not in sanitized

    def test_file_artifact_service_persists_base64_tool_output(self, tmp_path):
        config = Mock()
        config.MEDIA_DIR = tmp_path / "media"
        config.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        service = FileArtifactService(config=config)
        payload = base64.b64encode(b"artifact data" * 64).decode("ascii")

        result = service.maybe_persist_text_base64(payload, source="local")

        assert result is not None
        assert result.startswith("[Tool Returned File]")
        assert "source: local" in result

    def test_sanitize_tool_response_for_prompt_truncates_large_text(self, llm_client):
        """Very long tool output should be truncated before re-injection."""
        response = "x" * 13050

        sanitized = llm_client._sanitize_tool_response_for_prompt(response)

        assert "[tool output truncated, omitted" in sanitized
        assert len(sanitized) < len(response)

    def test_normalize_outbound_messages_rewrites_final_system_role(self, llm_client):
        messages = [
            {"role": "system", "content": "setup"},
            {"role": "system", "content": "respond to this"},
        ]

        normalized = llm_client._normalize_outbound_messages(messages)

        assert normalized[0]["role"] == "system"
        assert normalized[-1]["role"] == "user"
        assert normalized[-1]["content"] == "respond to this"
        assert messages[-1]["role"] == "system"

    def test_normalize_outbound_messages_keeps_final_tool_role(self, llm_client):
        messages = [
            {"role": "assistant", "content": "calling tool"},
            {"role": "tool", "content": "tool result", "tool_call_id": "1"},
        ]

        normalized = llm_client._normalize_outbound_messages(messages)

        assert normalized[-1]["role"] == "tool"

    def test_format_llm_exception_extracts_openai_error_message(self, llm_client):
        """Structured upstream errors should become readable RuntimeError messages."""

        class FakeError(Exception):
            def __init__(self):
                super().__init__("raw error")
                self.body = {
                    "error": {
                        "message": "maximum context length exceeded",
                        "code": 400,
                    }
                }

        message = llm_client._format_llm_exception(FakeError())

        assert "maximum context length exceeded" in message
        assert "code=400" in message

    @patch("llm.chat_client.get_cacheable_system_prompt", return_value="System prompt")
    @patch("llm.chat_client.get_current_time_str", return_value="2026-01-28 12:00:00")
    def test_build_chat_messages(self, mock_time, mock_system_prompt, llm_client):
        """Test building chat messages."""
        current_context = [
            {"role": "user", "content": "Previous message"},
            {"role": "user", "content": "Hello"},
        ]
        retrieved_summaries = ["Summary 1"]
        retrieved_conversations = ["Conversation 1"]

        messages = llm_client._build_chat_messages(
            current_context,
            retrieved_summaries,
            retrieved_conversations,
            current_session_id=123,
        )

        assert len(messages) == 6
        assert messages[0]["role"] == "system"
        assert "System prompt" in messages[0]["content"]
        assert messages[1]["role"] == "system"
        assert messages[1]["content"] == "<current_conversation>"
        assert messages[2]["role"] == "user"
        assert messages[2]["content"] == "Previous message"
        assert messages[3]["role"] == "system"
        assert messages[3]["content"] == "</current_conversation>"
        assert messages[4]["role"] == "system"
        assert "<extra_context>" in messages[4]["content"]
        assert "<similar_historical_summaries>" in messages[4]["content"]
        assert "Summary 1" in messages[4]["content"]
        assert "<similar_historical_conversations>" in messages[4]["content"]
        assert "Conversation 1" in messages[4]["content"]
        assert "<current_session_id>" in messages[4]["content"]
        assert "123" in messages[4]["content"]
        assert "<current_time>" in messages[4]["content"]
        assert "2026-01-28 12:00:00" in messages[4]["content"]
        assert messages[5]["role"] == "user"
        assert "<current_request>" in messages[5]["content"]
        assert "Now continue the current conversation" in messages[5]["content"]
        assert "Hello" in messages[5]["content"]

    @patch("llm.chat_client.AsyncOpenAI")
    @patch(
        "llm.chat_client.load_seele_json",
        return_value={"bot": {"name": "Seele"}, "user": {"name": "Alice"}},
    )
    @patch("llm.chat_client.get_summary_prompt", return_value="summary prompt")
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

    @patch("llm.chat_client.AsyncOpenAI")
    @patch(
        "llm.chat_client.load_seele_json",
        return_value={"bot": {"name": "Seele"}, "user": {"name": "Alice"}},
    )
    @patch("llm.chat_client.get_memory_update_prompt", return_value="memory prompt")
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

    @patch("llm.chat_client.AsyncOpenAI")
    @patch(
        "llm.chat_client.load_seele_json",
        return_value={"bot": {"name": "Seele"}, "user": {"name": "Alice"}},
    )
    @patch(
        "llm.chat_client.get_complete_memory_json_prompt",
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
            None,
        )

    @patch("llm.chat_client.AsyncOpenAI")
    @patch(
        "llm.chat_client.get_seele_compaction_prompt",
        return_value="compaction prompt",
    )
    def test_generate_seele_compaction(
        self, mock_get_prompt, mock_openai, llm_client
    ):
        """Test generating seele compaction request."""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = '{"personal_facts": [], "memorable_events": {}}'

        mock_async_client = AsyncMock()
        mock_async_client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )
        mock_openai.return_value = mock_async_client

        result = llm_client.generate_seele_compaction(
            '{"bot": {}, "user": {}, "memorable_events": {}, "commands_and_agreements": []}',
            20,
            20,
        )

        assert result == '{"personal_facts": [], "memorable_events": {}}'
        mock_get_prompt.assert_called_once_with(
            '{"bot": {}, "user": {}, "memorable_events": {}, "commands_and_agreements": []}',
            20,
            20,
        )

    @patch("llm.chat_client.AsyncOpenAI")
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
    async def test_chat_async_sanitizes_tool_output_before_reinjection(
        self, llm_client
    ):
        """Tool outputs should be sanitized before being appended to next LLM round."""
        base64_payload = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo+/=" * 64
        llm_client._build_chat_messages = Mock(
            return_value=[{"role": "user", "content": "Hello"}]
        )
        llm_client._tool_executor = AsyncMock(return_value=base64_payload)
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
                    "content": "done",
                    "tool_calls": None,
                    "api_tool_calls": None,
                    "reasoning_content": None,
                },
            ]
        )

        result = await llm_client.chat_async([], [], [])

        assert result == "done"
        second_call_messages = llm_client._async_chat.await_args_list[1].args[0]
        tool_message = second_call_messages[-1]
        assert tool_message["role"] == "tool"
        assert tool_message["content"].startswith(
            "[tool output omitted: detected large base64"
        )

    @pytest.mark.asyncio
    async def test_async_chat_wraps_exception_with_readable_message(self, llm_client):
        """_async_chat should raise a readable RuntimeError for upstream errors."""

        class FakeError(Exception):
            def __init__(self):
                super().__init__("raw error")
                self.body = {
                    "error": {
                        "message": "maximum context length exceeded",
                        "code": 400,
                    }
                }

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=FakeError())
        llm_client._chat_client = mock_client

        with pytest.raises(RuntimeError, match="maximum context length exceeded"):
            await llm_client._async_chat(
                [{"role": "user", "content": "hello"}],
                use_tools=False,
                force_chat_model=True,
            )

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
            "tool_context_messages": [],
            "conversation_events": [
                {
                    "event_index": 0,
                    "role": "assistant",
                    "content": "我先帮你查一下。",
                    "message_type": "conversation",
                },
                {
                    "event_index": 1,
                    "role": "assistant",
                    "content": "查到了，结果如下。",
                    "message_type": "conversation",
                },
            ],
        }

    @pytest.mark.asyncio
    @patch("llm.chat_client.AsyncOpenAI")
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
    @patch("llm.chat_client.AsyncOpenAI")
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

    @pytest.mark.asyncio
    @patch("llm.chat_client.AsyncOpenAI")
    async def test_async_chat_normalizes_final_system_role_before_request(
        self, mock_openai, llm_client
    ):
        """Provider-facing requests should never end with a system role."""
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

        await llm_client._async_chat(
            [
                {"role": "system", "content": "setup"},
                {"role": "system", "content": "final system instruction"},
            ],
            use_tools=False,
            force_chat_model=True,
        )

        create_kwargs = mock_async_client.chat.completions.create.await_args.kwargs
        assert create_kwargs["messages"][-1]["role"] == "user"
        assert create_kwargs["messages"][-1]["content"] == "final system instruction"


class TestDebugLogReduction:
    """Test log reduction when full prompt debug is enabled."""

    def test_request_executor_skips_content_preview_when_full_prompt_enabled(self):
        llm_client = Mock()
        llm_client._preview_text.return_value = "preview"
        executor = ChatRequestExecutor(llm_client)

        with patch("llm.request_executor.Config") as mock_config:
            with patch("llm.request_executor.logger") as mock_logger:
                mock_config.DEBUG_SHOW_FULL_PROMPT = True
                executor._log_response(
                    {
                        "tool_calls": None,
                        "content": "full content",
                        "api_tool_calls": None,
                        "reasoning_content": None,
                    }
                )

                debug_messages = [call.args[0] for call in mock_logger.debug.call_args_list]
                assert "LLM response contains no tool calls" in debug_messages
                assert not any(
                    message.startswith("LLM response content preview:")
                    for message in debug_messages
                )

    def test_request_executor_logs_full_response_when_full_prompt_enabled(self):
        llm_client = Mock()
        executor = ChatRequestExecutor(llm_client)

        with patch("llm.request_executor.Config") as mock_config:
            with patch("llm.request_executor.logger") as mock_logger:
                mock_config.DEBUG_SHOW_FULL_PROMPT = True
                executor._log_response(
                    {
                        "tool_calls": [
                            {"id": "call_1", "name": "demo_tool", "arguments": '{"q": "hi"}'}
                        ],
                        "content": "full content",
                        "api_tool_calls": None,
                        "reasoning_content": "full reasoning",
                    }
                )

                debug_messages = [call.args[0] for call in mock_logger.debug.call_args_list]
                assert any(
                    message.startswith("LLM response tool calls (full):")
                    for message in debug_messages
                )
                assert any(
                    message.startswith("LLM response content (full):")
                    for message in debug_messages
                )
                assert any(
                    message.startswith("LLM normalized response (full):")
                    for message in debug_messages
                )

    @pytest.mark.asyncio
    async def test_tool_loop_skips_intermediate_preview_when_full_prompt_enabled(self):
        llm_client = Mock()
        llm_client._async_chat = AsyncMock(
            side_effect=[
                {
                    "tool_calls": [{"name": "demo_tool", "arguments": "{}", "id": "1"}],
                    "content": "intermediate",
                },
                {"tool_calls": None, "content": "final"},
            ]
        )
        llm_client._extract_assistant_text_from_result.side_effect = [
            "intermediate",
            "final",
        ]
        llm_client._tool_executor = AsyncMock(return_value="tool output")
        llm_client._sanitize_tool_response_for_prompt.return_value = "tool output"
        llm_client._preview_text.return_value = "preview"
        llm_client._build_assistant_message_from_result.return_value = {"role": "assistant"}

        tool_loop = ToolLoop(llm_client)

        with patch("llm.tool_loop.Config") as mock_config:
            with patch("llm.tool_loop.logger") as mock_logger:
                mock_config.DEBUG_SHOW_FULL_PROMPT = True
                mock_config.TOOL_LOOP_MAX_ITERATIONS = 8
                await tool_loop.run_chat_with_tool_loop([{"role": "user", "content": "hi"}])

                debug_messages = [call.args[0] for call in mock_logger.debug.call_args_list]
                assert not any(
                    message.startswith(
                        "LLM emitted intermediate assistant text before tool execution:"
                    )
                    for message in debug_messages
                )
                assert any(
                    message.startswith(
                        "LLM emitted intermediate assistant text before tool execution (full):"
                    )
                    for message in debug_messages
                )

    @pytest.mark.asyncio
    async def test_tool_loop_logs_full_tool_details_when_full_prompt_enabled(self):
        llm_client = Mock()
        llm_client._async_chat = AsyncMock(
            side_effect=[
                {
                    "tool_calls": [
                        {"name": "demo_tool", "arguments": '{"x": 1}', "id": "1"}
                    ],
                    "content": "intermediate",
                },
                {"tool_calls": None, "content": "final"},
            ]
        )
        llm_client._extract_assistant_text_from_result.side_effect = [
            "intermediate",
            "final",
        ]
        llm_client._tool_executor = AsyncMock(
            return_value={"result": "tool output full", "context_message": "context full"}
        )
        llm_client._sanitize_tool_response_for_prompt.return_value = "tool output full"
        llm_client._build_assistant_message_from_result.return_value = {"role": "assistant"}

        tool_loop = ToolLoop(llm_client)

        with patch("llm.tool_loop.Config") as mock_config:
            with patch("llm.tool_loop.logger") as mock_logger:
                mock_config.DEBUG_SHOW_FULL_PROMPT = True
                mock_config.TOOL_LOOP_MAX_ITERATIONS = 8
                await tool_loop.run_chat_with_tool_loop([{"role": "user", "content": "hi"}])

                debug_messages = [call.args[0] for call in mock_logger.debug.call_args_list]
                assert any(
                    message.startswith("Executing tool call (full):")
                    for message in debug_messages
                )
                assert any(
                    message.startswith("Tool 'demo_tool' raw response (full):")
                    for message in debug_messages
                )
                assert any(
                    message.startswith("Tool 'demo_tool' sanitized response (full):")
                    for message in debug_messages
                )
                assert any(
                    message.startswith("Tool 'demo_tool' context message (full):")
                    for message in debug_messages
                )

    @pytest.mark.asyncio
    async def test_tool_loop_stops_after_max_iterations(self):
        llm_client = Mock()
        llm_client._async_chat = AsyncMock(
            return_value={
                "tool_calls": [{"name": "demo_tool", "arguments": "{}", "id": "1"}],
                "content": "still using tools",
            }
        )
        llm_client._extract_assistant_text_from_result.return_value = "still using tools"
        llm_client._tool_executor = AsyncMock(return_value="tool output")
        llm_client._sanitize_tool_response_for_prompt.return_value = "tool output"
        llm_client._preview_text.return_value = "preview"
        llm_client._build_assistant_message_from_result.return_value = {"role": "assistant"}

        tool_loop = ToolLoop(llm_client)

        with patch("llm.tool_loop.Config") as mock_config:
            mock_config.DEBUG_SHOW_FULL_PROMPT = False
            mock_config.TOOL_LOOP_MAX_ITERATIONS = 2

            result = await tool_loop.run_chat_with_tool_loop(
                [{"role": "user", "content": "hi"}]
            )

        assert result["final_text"].startswith("[System Event] Tool loop stopped")
        # Verify the conversation event uses system role, not assistant
        stop_events = [
            e
            for e in result["conversation_events"]
            if "Tool loop stopped" in e["content"]
        ]
        assert len(stop_events) == 1
        assert stop_events[0]["role"] == "system"
        assert llm_client._tool_executor.await_count == 2
        assert llm_client._async_chat.await_count == 3
