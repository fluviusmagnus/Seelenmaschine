"""Integration tests using test.env configuration

These tests use the test.env profile to verify complete system integration
without making real API calls (using mocks).
"""

import sys
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
import pytest
import json

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture(scope="module")
def test_config():
    """Initialize test configuration from test.env"""
    from config import init_config, Config
    from zoneinfo import ZoneInfo
    
    # Save original values
    original_timezone = Config.TIMEZONE
    original_timezone_str = Config.TIMEZONE_STR
    
    # Initialize with test profile
    init_config("test")
    
    yield Config
    
    # Cleanup after tests - restore original values
    Config._initialized = False
    Config.TIMEZONE = original_timezone
    Config.TIMEZONE_STR = original_timezone_str


class TestSystemInitialization:
    """Test complete system initialization with test.env"""
    
    def test_config_loaded_from_test_env(self, test_config):
        """Verify test.env configuration is loaded correctly"""
        assert test_config.DEBUG_MODE == True
        assert test_config.DEBUG_LOG_LEVEL == "INFO"
        assert test_config.TIMEZONE_STR == "Europe/Berlin"
        assert test_config.PROFILE == "test"
        assert test_config.DATA_DIR is not None
        assert test_config.DB_PATH is not None
    
    def test_data_directory_structure(self, test_config):
        """Test that data directory structure is created"""
        # Verify data directories exist
        assert test_config.DATA_DIR.exists()
        assert (test_config.DATA_DIR / "..").exists()
    
    def test_database_initialization(self, test_config):
        """Test database initialization with test profile"""
        from core.database import DatabaseManager
        
        db = DatabaseManager()
        
        # Verify database connection
        assert db.db_path == test_config.DB_PATH
        
        # Verify schema version
        version = db.get_schema_version()
        assert version is not None
        assert version.startswith("3.")  # Schema 3.x


class TestMessageHandlerIntegration:
    """Test MessageHandler with test configuration"""
    
    @pytest.fixture
    def mock_llm_for_test(self):
        """Create mock LLM client for testing"""
        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "Test AI response"
        mock_response.choices[0].message.tool_calls = None
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        return mock_client
    
    @pytest.mark.skip(reason="Requires async setup with test profile")
    def test_message_handler_initialization(self, test_config):
        """Test MessageHandler initializes with test config"""
        # This would test that MessageHandler can be initialized
        # with the test configuration
        pass


class TestMemoryManagerIntegration:
    """Test MemoryManager with test configuration"""
    
    @pytest.fixture
    def mock_embedding_for_test(self):
        """Create mock embedding client"""
        mock_client = Mock()
        mock_client.get_embedding.return_value = [0.1] * 1536
        mock_client.get_embedding_async = AsyncMock(return_value=[0.1] * 1536)
        return mock_client
    
    def test_memory_manager_with_test_db(self, test_config, mock_embedding_for_test):
        """Test MemoryManager uses test database"""
        from core.memory import MemoryManager
        from core.database import DatabaseManager
        
        db = DatabaseManager()
        
        with patch('config.Config.CONTEXT_WINDOW_TRIGGER_SUMMARY', 32):
            with patch('config.Config.CONTEXT_WINDOW_KEEP_MIN', 16):
                mm = MemoryManager(
                    db=db,
                    embedding_client=mock_embedding_for_test,
                    reranker_client=Mock()
                )
                
                # Verify initialization
                assert mm is not None
                assert mm.get_current_session_id() is not None


class TestSchedulerIntegration:
    """Test TaskScheduler with test configuration"""
    
    def test_scheduler_with_test_config(self, test_config):
        """Test TaskScheduler uses test configuration"""
        from core.scheduler import TaskScheduler
        from core.database import DatabaseManager
        
        db = DatabaseManager()
        scheduler = TaskScheduler(db)
        
        # Verify scheduler initialized
        assert scheduler is not None
        assert scheduler.db is not None


class TestContextWindowIntegration:
    """Test ContextWindow with test config settings"""
    
    def test_context_window_respects_config_limits(self, test_config):
        """Test ContextWindow respects CONTEXT_WINDOW_TRIGGER_SUMMARY"""
        from core.context import ContextWindow
        from core.memory import MemoryManager
        
        # Create context window
        ctx = ContextWindow()
        
        # Add messages up to trigger limit
        trigger_count = test_config.CONTEXT_WINDOW_TRIGGER_SUMMARY
        
        for i in range(trigger_count):
            ctx.add_message("user" if i % 2 == 0 else "assistant", f"Message {i}")
        
        # Verify message count
        assert ctx.get_total_message_count() == trigger_count


class TestToolsIntegration:
    """Test tools integration with test configuration"""
    
    def test_memory_search_tool_with_test_config(self, test_config):
        """Test MemorySearchTool uses test configuration"""
        from tools.memory_search import MemorySearchTool
        from core.database import DatabaseManager
        
        db = DatabaseManager()
        
        # Create tool with test config
        tool = MemorySearchTool(
            session_id="1",
            db=db,
            embedding_client=Mock(),
            reranker_client=Mock()
        )
        
        # Verify tool initialized
        assert tool is not None
        assert tool.name == "search_memories"
    
    def test_scheduled_task_tool_with_test_config(self, test_config):
        """Test ScheduledTaskTool uses test configuration"""
        from tools.scheduled_task_tool import ScheduledTaskTool
        from core.scheduler import TaskScheduler
        from core.database import DatabaseManager
        
        db = DatabaseManager()
        scheduler = TaskScheduler(db)
        
        # Create tool
        tool = ScheduledTaskTool(scheduler)
        
        # Verify tool initialized
        assert tool is not None
        assert tool.name == "scheduled_task"


class TestPromptsIntegration:
    """Test prompts with test configuration"""
    
    def test_system_prompt_uses_test_config(self, test_config):
        """Test system prompt generation uses test config"""
        from prompts.system import get_cacheable_system_prompt
        
        # Clear cache to force reload
        import prompts.system
        prompts.system._seele_json_cache = {}
        
        # Generate prompt
        prompt = get_cacheable_system_prompt(recent_summaries=[])
        
        # Verify prompt generated
        assert isinstance(prompt, str)
        assert len(prompt) > 0


class TestEndToEndFlow:
    """End-to-end integration tests using test.env"""
    
    @pytest.mark.skip(reason="Requires full system with mocked LLM")
    def test_complete_conversation_flow(self, test_config):
        """Test complete conversation flow:
        
        1. User sends message
        2. Message stored in database
        3. Context retrieved
        4. LLM called (mocked)
        5. Response stored
        6. Response returned
        """
        pass
    
    @pytest.mark.skip(reason="Requires full system with time control")
    def test_scheduled_task_execution_flow(self, test_config):
        """Test scheduled task execution:
        
        1. Task created
        2. Task stored in database
        3. Time passes (mocked)
        4. Task triggered
        5. Message sent
        """
        pass
    
    @pytest.mark.skip(reason="Requires memory summarization with mocked LLM")
    def test_memory_summarization_flow(self, test_config):
        """Test automatic memory summarization:
        
        1. Add messages up to trigger count
        2. Summary automatically created
        3. Long-term memory updated
        4. Old messages marked as summarized
        """
        pass


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
