"""Integration tests using test.env configuration

These tests use the test.env profile to verify complete system integration
without making real API calls (using mocks).
"""

from unittest.mock import Mock, patch, AsyncMock
import pytest


@pytest.fixture(scope="module")
def test_config():
    """Initialize test configuration from test.env"""
    from core.config import init_config, Config

    # Save original values
    original_initialized = Config._initialized
    original_profile = Config.PROFILE
    original_timezone = Config.TIMEZONE
    original_timezone_str = Config.TIMEZONE_STR

    # Force re-initialization for this fixture.
    Config._initialized = False

    # Initialize with test profile
    init_config("test")

    yield Config

    # Cleanup after tests - restore original values
    Config._initialized = original_initialized
    Config.PROFILE = original_profile
    Config.TIMEZONE = original_timezone
    Config.TIMEZONE_STR = original_timezone_str


class TestSystemInitialization:
    """Test complete system initialization with the test profile."""
    
    def test_config_loaded_from_test_env(self, test_config):
        """Verify test profile initialization sets expected derived paths."""
        assert test_config.PROFILE == "test"
        assert isinstance(test_config.TIMEZONE_STR, str)
        assert len(test_config.TIMEZONE_STR) > 0
        assert test_config.DATA_DIR is not None
        assert test_config.DB_PATH is not None
        assert test_config.DATA_DIR.name == "test"
        assert test_config.DB_PATH.parent == test_config.DATA_DIR
    
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
        from memory.manager import MemoryManager
        from core.database import DatabaseManager
        
        db = DatabaseManager()
        
        with patch('core.config.Config.CONTEXT_WINDOW_TRIGGER_SUMMARY', 32):
            with patch('core.config.Config.CONTEXT_WINDOW_KEEP_MIN', 16):
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
        from memory.context import ContextWindow
        
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
        from tools.scheduled_tasks import ScheduledTaskTool
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
        from prompts import get_cacheable_system_prompt
        
        # Clear cache to force reload
        import prompts
        prompts._seele_json_cache = {}
        
        # Generate prompt
        prompt = get_cacheable_system_prompt(recent_summaries=[])
        
        # Verify prompt generated
        assert isinstance(prompt, str)
        assert len(prompt) > 0


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])



