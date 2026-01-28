"""Test for MessageHandler with message processing"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from unittest.mock import Mock, patch, AsyncMock
from tg_bot.handlers import MessageHandler


@pytest.fixture
def mock_config():
    """Mock Config"""
    with patch('tg_bot.handlers.Config') as mock:
        config_instance = Mock()
        config_instance.ENABLE_SKILLS = True
        config_instance.ENABLE_MCP = False
        config_instance.TELEGRAM_USER_ID = 12345
        config_instance.TELEGRAM_USE_MARKDOWN = True
        mock.return_value = config_instance
        yield config_instance


@pytest.fixture
def mock_db():
    """Mock DatabaseManager"""
    with patch('tg_bot.handlers.DatabaseManager') as mock:
        db_instance = Mock()
        db_instance.get_active_session.return_value = {"session_id": 1}
        mock.return_value = db_instance
        yield db_instance


@pytest.fixture
def mock_embedding_client():
    """Mock EmbeddingClient"""
    with patch('tg_bot.handlers.EmbeddingClient') as mock:
        client = Mock()
        client.get_embedding.return_value = [0.1] * 1536
        mock.return_value = client
        yield client


@pytest.fixture
def mock_reranker_client():
    """Mock RerankerClient"""
    with patch('tg_bot.handlers.RerankerClient') as mock:
        client = Mock()
        client.is_enabled.return_value = False
        mock.return_value = client
        yield client


@pytest.fixture
def mock_memory():
    """Mock MemoryManager"""
    with patch('tg_bot.handlers.MemoryManager') as mock:
        memory = Mock()
        memory.get_current_session_id.return_value = 1
        memory.get_context_messages.return_value = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"}
        ]
        memory.get_recent_summaries.return_value = []
        # Return async mock for async methods
        memory.add_user_message_async = AsyncMock(return_value=(1, [0.1] * 1536))
        memory.process_user_input_async = AsyncMock(return_value=([], []))
        memory.add_assistant_message_async = AsyncMock(return_value=(1, None))
        memory.new_session = Mock(return_value=2)
        memory.reset_session = Mock()
        mock.return_value = memory
        yield memory


@pytest.fixture
def mock_llm_client():
    """Mock LLMClient"""
    with patch('tg_bot.handlers.LLMClient') as mock:
        client = Mock()
        client.chat_async = AsyncMock(return_value="This is a test response")
        client.set_tools = Mock()
        client.set_tool_executor = Mock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_scheduler():
    """Mock TaskScheduler"""
    with patch('tg_bot.handlers.TaskScheduler') as mock:
        scheduler = Mock()
        mock.return_value = scheduler
        yield scheduler


@pytest.fixture
def mock_skill_manager():
    """Mock SkillManager"""
    with patch('tg_bot.handlers.SkillManager') as mock:
        manager = Mock()
        manager._skills = {}
        manager.get_tools.return_value = []
        mock.return_value = manager
        yield manager


def test_message_handler_initialization(
    mock_config,
    mock_db,
    mock_embedding_client,
    mock_reranker_client,
    mock_memory,
    mock_llm_client,
    mock_scheduler,
    mock_skill_manager
):
    """Test MessageHandler initializes correctly"""
    handler = MessageHandler()
    
    assert handler.config is not None
    assert handler.db is not None
    assert handler.memory is not None
    assert handler.llm_client is not None
    assert handler.scheduler is not None
    assert handler.skill_manager is not None


@pytest.mark.asyncio
async def test_process_message(
    mock_config,
    mock_db,
    mock_embedding_client,
    mock_reranker_client,
    mock_memory,
    mock_llm_client,
    mock_scheduler,
    mock_skill_manager
):
    """Test _process_message flow"""
    handler = MessageHandler()
    
    # Test processing a message
    response = await handler._process_message("Hello, how are you?")
    
    # Verify the response
    assert response == "This is a test response"
    
    # Verify memory operations were called (async methods)
    # Note: handler.memory is the actual instance returned by mock_memory.return_value
    handler.memory.add_user_message_async.assert_called_once_with("Hello, how are you?")
    handler.memory.get_context_messages.assert_called_once()
    handler.memory.process_user_input_async.assert_called_once()
    handler.memory.add_assistant_message_async.assert_called_once_with("This is a test response")


@pytest.mark.asyncio
async def test_handle_message(
    mock_config,
    mock_db,
    mock_embedding_client,
    mock_reranker_client,
    mock_memory,
    mock_llm_client,
    mock_scheduler,
    mock_skill_manager
):
    """Test handle_message with Telegram update"""
    handler = MessageHandler()
    
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
    mock_config,
    mock_db,
    mock_embedding_client,
    mock_reranker_client,
    mock_memory,
    mock_llm_client,
    mock_scheduler,
    mock_skill_manager
):
    """Test /new command handler"""
    handler = MessageHandler()
    
    # Mock Telegram update with AsyncMock
    update = Mock()
    update.effective_user.id = 12345
    update.message.reply_text = AsyncMock()
    
    context = Mock()
    
    # Mock the async version of new_session
    handler.memory.new_session_async = AsyncMock(return_value=2)
    
    # Handle new session command
    await handler.handle_new_session(update, context)
    
    # Verify new session was created (should call async version)
    handler.memory.new_session_async.assert_called_once()
    update.message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_handle_reset_session(
    mock_config,
    mock_db,
    mock_embedding_client,
    mock_reranker_client,
    mock_memory,
    mock_llm_client,
    mock_scheduler,
    mock_skill_manager
):
    """Test /reset command handler"""
    handler = MessageHandler()
    
    # Mock Telegram update with AsyncMock
    update = Mock()
    update.effective_user.id = 12345
    update.message.reply_text = AsyncMock()
    
    context = Mock()
    
    # Handle reset session command
    await handler.handle_reset_session(update, context)
    
    # Verify session was reset
    handler.memory.reset_session.assert_called_once()
    update.message.reply_text.assert_called_once()


def test_execute_tool_memory_search(
    mock_config,
    mock_db,
    mock_embedding_client,
    mock_reranker_client,
    mock_memory,
    mock_llm_client,
    mock_scheduler,
    mock_skill_manager
):
    """Test tool execution for memory search"""
    handler = MessageHandler()
    
    # Mock memory search tool
    handler.memory_search_tool = Mock()
    handler.memory_search_tool.name = "search_memories"
    handler.memory_search_tool.execute_sync.return_value = "Found memories"
    
    # Execute tool
    result = handler._execute_tool("search_memories", '{"query": "test"}')
    
    assert result == "Found memories"
    handler.memory_search_tool.execute_sync.assert_called_once_with(query="test")


def test_execute_tool_skill(
    mock_config,
    mock_db,
    mock_embedding_client,
    mock_reranker_client,
    mock_memory,
    mock_llm_client,
    mock_scheduler,
    mock_skill_manager
):
    """Test tool execution for skills"""
    handler = MessageHandler()
    
    # Mock a skill
    mock_skill = Mock()
    handler.skill_manager._skills["test_skill"] = mock_skill
    handler.skill_manager.execute_skill_sync.return_value = "Skill result"
    
    # Execute tool
    result = handler._execute_tool("test_skill", '{"param": "value"}')
    
    assert result == "Skill result"
    handler.skill_manager.execute_skill_sync.assert_called_once_with("test_skill", {"param": "value"})


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
