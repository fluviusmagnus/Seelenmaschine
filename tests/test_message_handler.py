"""Test for TelegramController with message processing."""

import asyncio
import sys
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from adapter.telegram.controller import TelegramController
from adapter.telegram.formatter import TelegramResponseFormatter
from core.bot import CoreBot


@pytest.fixture
def mock_config(tmp_path):
    """Mock Config"""
    config_instance = Mock()
    config_instance.ENABLE_MCP = False
    config_instance.TELEGRAM_USER_ID = 12345
    config_instance.TELEGRAM_USE_MARKDOWN = True
    config_instance.DEBUG_MODE = False
    config_instance.DATA_DIR = tmp_path
    config_instance.WORKSPACE_DIR = tmp_path / "workspace"
    config_instance.MEDIA_DIR = tmp_path / "workspace" / "media"
    return config_instance


@pytest.fixture
def mock_db():
    """Mock DatabaseManager"""
    db_instance = Mock()
    db_instance.get_active_session.return_value = {"session_id": 1}
    return db_instance


@pytest.fixture
def mock_embedding_client():
    """Mock EmbeddingClient"""
    client = Mock()
    client.get_embedding.return_value = [0.1] * 1536
    client.get_embedding_async = AsyncMock(return_value=[0.1] * 1536)
    return client


@pytest.fixture
def mock_reranker_client():
    """Mock RerankerClient"""
    client = Mock()
    client.is_enabled.return_value = False
    return client


@pytest.fixture
def mock_memory():
    """Mock MemoryManager"""
    memory = Mock()
    memory.get_current_session_id.return_value = 1
    memory.get_context_messages.return_value = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]
    memory.get_recent_summaries.return_value = []
    memory.add_user_message_async = AsyncMock(return_value=(1, [0.1] * 1536))
    memory.process_user_input_async = AsyncMock(return_value=([], []))
    memory.add_assistant_message_async = AsyncMock(return_value=(1, None))
    memory.run_summary_check_async = AsyncMock(return_value=None)
    memory.new_session = Mock(return_value=2)
    memory.new_session_async = AsyncMock(return_value=2)
    memory.reset_session = Mock()
    return memory


@pytest.fixture
def mock_llm_client():
    """Mock LLMClient"""
    client = Mock()
    client.chat_async_detailed = AsyncMock(
        return_value={
            "final_text": "This is a test response",
            "assistant_messages": ["This is a test response"],
            "tool_context_messages": [],
            "conversation_events": [
                {"role": "assistant", "content": "This is a test response"}
            ],
        }
    )
    client.set_tools = Mock()
    client.set_tool_executor = Mock()
    return client


@pytest.fixture
def mock_scheduler():
    """Mock TaskScheduler"""
    scheduler = Mock()
    return scheduler


@pytest.fixture
def core_bot(
    mock_config,
    mock_db,
    mock_embedding_client,
    mock_reranker_client,
    mock_memory,
    mock_llm_client,
    mock_scheduler,
):
    return CoreBot(
        config=mock_config,
        db=mock_db,
        embedding_client=mock_embedding_client,
        reranker_client=mock_reranker_client,
        memory=mock_memory,
        scheduler=mock_scheduler,
        llm_client=mock_llm_client,
    )


def test_message_handler_initialization(
    core_bot,
):
    """Test TelegramController initializes correctly"""
    handler = TelegramController(core_bot=core_bot)

    assert handler.core_bot.config is not None
    assert handler.core_bot.db is not None
    assert handler.core_bot.memory is not None
    assert handler.core_bot.llm_client is not None
    assert handler.core_bot.scheduler is not None


@pytest.mark.asyncio
async def test_process_message(
    core_bot,
):
    """Test message processing flow via the Telegram message service."""
    handler = TelegramController(core_bot=core_bot)

    response = await handler.messages.process_message("Hello, how are you?")

    # Verify the response
    assert response == "This is a test response"

    # Verify memory operations were called (async methods)
    # Note: handler.memory is the actual instance returned by mock_memory.return_value
    handler.core_bot.memory.add_user_message_async.assert_called_once_with(
        "Hello, how are you?",
        embedding=None,
    )
    handler.core_bot.memory.get_context_messages.assert_called_once()
    handler.core_bot.memory.process_user_input_async.assert_called_once()
    handler.core_bot.memory.add_assistant_message_async.assert_called_once_with(
        "This is a test response"
    )
    handler.core_bot.memory.run_summary_check_async.assert_not_called()


@pytest.mark.asyncio
async def test_process_message_with_embedding_override(
    core_bot,
):
    """Test message processing forwards explicit embedding text override."""
    handler = TelegramController(core_bot=core_bot)

    response = await handler.messages.process_message(
        "Hello, how are you?",
        message_for_embedding="caption text",
    )

    assert response == "This is a test response"
    handler.core_bot.memory.add_user_message_async.assert_called_once_with(
        "Hello, how are you?",
        embedding=[0.1] * 1536,
    )


@pytest.mark.asyncio
async def test_handle_message(
    core_bot,
):
    """Test handle_message with Telegram update"""
    handler = TelegramController(core_bot=core_bot)

    # Mock Telegram update with AsyncMock for async methods
    update = Mock()
    update.effective_user.id = 12345
    update.message.text = "Hello"
    update.message.chat.send_action = AsyncMock()
    update.message.reply_text = AsyncMock()

    context = Mock()
    context.bot = Mock()
    context.bot.send_chat_action = AsyncMock()

    # Handle message
    await handler.handle_message(update, context)

    # Verify reply was sent
    update.message.reply_text.assert_called_once()
    call_args = update.message.reply_text.call_args
    assert "This is a test response" in str(call_args)
    handler.core_bot.memory.run_summary_check_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_new_session(
    core_bot,
):
    """Test /new command handler"""
    handler = TelegramController(core_bot=core_bot)

    started = asyncio.Event()
    release = asyncio.Event()

    async def _new_session_side_effect():
        started.set()
        await release.wait()
        return 2

    handler.core_bot.memory.new_session_async = AsyncMock(
        side_effect=_new_session_side_effect
    )

    # Mock Telegram update with AsyncMock
    update = Mock()
    update.effective_user.id = 12345
    update.message.reply_text = AsyncMock()

    context = Mock()
    context.bot = Mock()
    context.bot.send_chat_action = AsyncMock()

    task = asyncio.create_task(handler.commands.handle_new_session(update, context))
    await started.wait()
    await asyncio.sleep(0.05)
    release.set()
    await task

    handler.core_bot.memory.new_session_async.assert_called_once()
    update.message.reply_text.assert_called_once()
    context.bot.send_chat_action.assert_awaited()


@pytest.mark.asyncio
async def test_handle_new_session_returns_error_details(core_bot):
    """/new should surface formatted error details to the user."""
    handler = TelegramController(core_bot=core_bot)
    handler.core_bot.memory.new_session_async = AsyncMock(
        side_effect=RuntimeError("Session storage unavailable")
    )

    update = Mock()
    update.effective_user.id = 12345
    update.effective_chat.id = 12345
    update.message.reply_text = AsyncMock()

    context = Mock()
    context.bot = Mock()
    context.bot.send_chat_action = AsyncMock()

    await handler.commands.handle_new_session(update, context)

    sent_text = update.message.reply_text.await_args.args[0]
    assert "Error creating new session." in sent_text
    assert "RuntimeError: Session storage unavailable" in sent_text


@pytest.mark.asyncio
async def test_handle_reset_session(
    core_bot,
):
    """Test /reset command handler"""
    handler = TelegramController(core_bot=core_bot)

    # Mock Telegram update with AsyncMock
    update = Mock()
    update.effective_user.id = 12345
    update.message.reply_text = AsyncMock()

    context = Mock()

    await handler.commands.handle_reset_session(update, context)

    # Verify session was reset
    handler.core_bot.memory.reset_session.assert_called_once()
    update.message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_handle_reset_session_returns_error_details(core_bot):
    """/reset should surface formatted error details to the user."""
    handler = TelegramController(core_bot=core_bot)
    handler.core_bot.memory.reset_session = Mock(side_effect=KeyError("error"))

    update = Mock()
    update.effective_user.id = 12345
    update.message.reply_text = AsyncMock()

    context = Mock()

    await handler.commands.handle_reset_session(update, context)

    sent_text = update.message.reply_text.await_args.args[0]
    assert "Error resetting session." in sent_text
    assert "Missing expected field: error" in sent_text


def test_execute_tool_memory_search(
    core_bot,
):
    """Test tool execution for memory search"""
    handler = TelegramController(core_bot=core_bot)

    memory_search_tool = Mock()
    memory_search_tool.name = "search_memories"
    memory_search_tool.execute = AsyncMock(return_value="Found memories")
    handler.core_bot.tool_runtime_state.registry_service.register_named(
        "search_memories", memory_search_tool
    )

    import asyncio

    result = asyncio.run(core_bot.execute_tool("search_memories", '{"query": "test"}'))

    assert result["result"] == "Found memories"
    assert "[Tool Call]" in result["context_message"]
    assert 'status: "success"' in result["context_message"]
    assert 'tool_name: "search_memories"' in result["context_message"]
    assert "arguments_preview:" in result["context_message"]
    assert "result_preview:" in result["context_message"]
    memory_search_tool.execute.assert_called_once_with(query="test")

    trace_path = handler.core_bot.config.DATA_DIR / "tool_traces.jsonl"
    assert trace_path.exists()
    records = [
        json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 1
    assert records[0]["tool_name"] == "search_memories"
    assert records[0]["status"] == "success"


def test_query_tool_history_is_not_self_logged(
    core_bot,
):
    """query_tool_history should not create recursive log entries."""
    handler = TelegramController(core_bot=core_bot)

    import asyncio

    result = asyncio.run(core_bot.execute_tool("query_tool_history", "{}"))

    assert "No tool history records found." in result["result"]
    trace_path = handler.core_bot.config.DATA_DIR / "tool_traces.jsonl"
    if trace_path.exists():
        assert trace_path.read_text(encoding="utf-8").strip() == ""


@pytest.mark.asyncio
async def test_non_dangerous_tool_sends_telegram_notification(core_bot):
    """Non-dangerous tool calls should proactively notify the Telegram user."""
    handler = TelegramController(core_bot=core_bot)
    handler.telegram_bot = Mock()
    handler.telegram_bot.send_message = AsyncMock()

    read_tool = Mock()
    read_tool.name = "read_file"
    read_tool.execute = AsyncMock(return_value="file content")
    handler.core_bot.tool_runtime_state.registry_service.register_named(
        "read_file", read_tool
    )

    result = await core_bot.execute_tool("read_file", '{"file_path": "notes.txt"}')
    await __import__("asyncio").sleep(0)

    assert result["result"] == "file content"
    assert "trace_id:" in result["context_message"]
    assert 'tool_name: "read_file"' in result["context_message"]
    read_tool.execute.assert_awaited_once_with(file_path="notes.txt")
    handler.telegram_bot.send_message.assert_awaited()

    sent_texts = [
        call.kwargs["text"]
        for call in handler.telegram_bot.send_message.await_args_list
    ]
    assert any("Tool execution:" in text for text in sent_texts)
    assert any("read_file" in text for text in sent_texts)


def test_formatter_module_replaces_handler_format_wrapper():
    """Formatting should now be tested through the formatter directly."""
    formatter = TelegramResponseFormatter()

    assert formatter.format_response("**hi**", debug_mode=True) == "<b>hi</b>"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
