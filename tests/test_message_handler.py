"""Test for MessageHandler with message processing"""

import sys
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from adapter.telegram.handlers import MessageHandler
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
    """Test MessageHandler initializes correctly"""
    handler = MessageHandler(core_bot=core_bot)

    assert handler.core_bot.config is not None
    assert handler.core_bot.db is not None
    assert handler.core_bot.memory is not None
    assert handler.core_bot.llm_client is not None
    assert handler.core_bot.scheduler is not None


@pytest.mark.asyncio
async def test_process_message(
    core_bot,
):
    """Test _process_message flow"""
    handler = MessageHandler(core_bot=core_bot)

    # Test processing a message
    response = await handler._process_message("Hello, how are you?")

    # Verify the response
    assert response == "This is a test response"

    # Verify memory operations were called (async methods)
    # Note: handler.memory is the actual instance returned by mock_memory.return_value
    handler.core_bot.memory.add_user_message_async.assert_called_once_with(
        "Hello, how are you?"
    )
    handler.core_bot.memory.get_context_messages.assert_called_once()
    handler.core_bot.memory.process_user_input_async.assert_called_once()
    handler.core_bot.memory.add_assistant_message_async.assert_called_once_with(
        "This is a test response"
    )


@pytest.mark.asyncio
async def test_handle_message(
    core_bot,
):
    """Test handle_message with Telegram update"""
    handler = MessageHandler(core_bot=core_bot)

    # Mock Telegram update with AsyncMock for async methods
    update = Mock()
    update.effective_user.id = 12345
    update.message.text = "Hello"
    update.message.chat.send_action = AsyncMock()
    update.message.reply_text = AsyncMock()

    context = Mock()

    # Handle message
    await handler.handle_message(update, context)

    # Verify reply was sent
    update.message.reply_text.assert_called_once()
    call_args = update.message.reply_text.call_args
    assert "This is a test response" in str(call_args)


@pytest.mark.asyncio
async def test_handle_new_session(
    core_bot,
):
    """Test /new command handler"""
    handler = MessageHandler(core_bot=core_bot)

    # Mock Telegram update with AsyncMock
    update = Mock()
    update.effective_user.id = 12345
    update.message.reply_text = AsyncMock()

    context = Mock()

    # Mock the async version of new_session
    handler.core_bot.memory.new_session_async = AsyncMock(return_value=2)

    # Handle new session command
    await handler.handle_new_session(update, context)

    # Verify new session was created (should call async version)
    handler.core_bot.memory.new_session_async.assert_called_once()
    update.message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_handle_reset_session(
    core_bot,
):
    """Test /reset command handler"""
    handler = MessageHandler(core_bot=core_bot)

    # Mock Telegram update with AsyncMock
    update = Mock()
    update.effective_user.id = 12345
    update.message.reply_text = AsyncMock()

    context = Mock()

    # Handle reset session command
    await handler.handle_reset_session(update, context)

    # Verify session was reset
    handler.core_bot.memory.reset_session.assert_called_once()
    update.message.reply_text.assert_called_once()


def test_execute_tool_memory_search(
    core_bot,
):
    """Test tool execution for memory search"""
    handler = MessageHandler(core_bot=core_bot)

    # Mock memory search tool and update the registry
    memory_search_tool = Mock()
    memory_search_tool.name = "search_memories"
    memory_search_tool.execute = AsyncMock(return_value="Found memories")
    handler.tool_runtime_state.memory_search_tool = memory_search_tool
    handler._tool_registry["search_memories"] = memory_search_tool

    # Execute tool (should await the result)
    import asyncio

    result = asyncio.run(handler._execute_tool("search_memories", '{"query": "test"}'))

    assert result == "Found memories"
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
    handler = MessageHandler(core_bot=core_bot)

    import asyncio

    result = asyncio.run(handler._execute_tool("query_tool_history", "{}"))

    assert "No tool history records found." in result
    trace_path = handler.core_bot.config.DATA_DIR / "tool_traces.jsonl"
    if trace_path.exists():
        assert trace_path.read_text(encoding="utf-8").strip() == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
