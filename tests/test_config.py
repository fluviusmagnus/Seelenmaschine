import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, Mock

from config import Config, init_config


@pytest.fixture
def reset_config():
    """Reset Config between tests."""
    Config._initialized = False
    Config._profile = None
    yield
    Config._initialized = False
    Config._profile = None


@pytest.fixture
def temp_env_file(reset_config):
    """Create a temporary .env file for testing."""
    import uuid

    filename = f"test_{uuid.uuid4().hex[:8]}.env"
    temp_path = Path.cwd() / filename
    with open(temp_path, "w") as f:
        f.write("DEBUG_MODE=true\n")
        f.write("DEBUG_LOG_LEVEL=DEBUG\n")
        f.write("OPENAI_API_KEY=test-api-key\n")
        f.write("OPENAI_API_BASE=https://test.api.com/v1\n")
        f.write("CHAT_MODEL=gpt-4-test\n")
        f.write("TOOL_MODEL=gpt-4-tool\n")
        f.write("EMBEDDING_MODEL=text-embedding-test\n")
        f.write("EMBEDDING_DIMENSION=768\n")
        f.write("TIMEZONE=UTC\n")
        f.write("CONTEXT_WINDOW_KEEP_MIN=10\n")
        f.write("CONTEXT_WINDOW_TRIGGER_SUMMARY=20\n")
        f.write("RECENT_SUMMARIES_MAX=5\n")
        f.write("RECALL_SUMMARY_PER_QUERY=5\n")
        f.write("RECALL_CONV_PER_SUMMARY=6\n")
        f.write("RERANK_TOP_SUMMARIES=5\n")
        f.write("RERANK_TOP_CONVS=10\n")
        f.write("NEW_SESSION_COMMAND=/newtest\n")
        f.write("RESET_SESSION_COMMAND=/resettest\n")
        f.write("TELEGRAM_BOT_TOKEN=test-token\n")
        f.write("TELEGRAM_USER_ID=999999\n")
        f.write("TELEGRAM_USE_MARKDOWN=false\n")
        f.write("ENABLE_SKILLS=false\n")
        f.write("ENABLE_MCP=true\n")
        f.write("ENABLE_WEB_SEARCH=true\n")
        f.write("JINA_API_KEY=jina-test-key\n")
    yield filename
    if temp_path.exists():
        temp_path.unlink()


class TestConfig:
    """Test Config class functionality."""

    def test_config_defaults_before_init(self, reset_config):
        """Test default values before initialization."""
        assert Config.PROFILE == "default"
        assert Config.DATA_DIR == Path.cwd() / "data" / "default"
        assert Config.DEBUG_MODE is False
        assert Config.DEBUG_LOG_LEVEL == "INFO"
        assert Config.TIMEZONE_STR == "Asia/Shanghai"
        assert Config.CHAT_MODEL == "gpt-4o"
        assert Config.TOOL_MODEL == "gpt-4o"
        assert Config.EMBEDDING_DIMENSION == 1536

    def test_init_creates_data_dir(self, reset_config):
        """Test that init creates data directory."""
        with patch.object(Config, "_load_env"):
            with patch.object(Config, "_load_all_settings"):
                init_config("test_profile")
                assert Config.DATA_DIR.exists()

    def test_init_sets_profile(self, reset_config):
        """Test that init sets profile."""
        with patch.object(Config, "_load_env"):
            with patch.object(Config, "_load_all_settings"):
                with patch.object(Config, "_ensure_dirs_exist"):
                    init_config("test_profile")
                    assert Config.PROFILE == "test_profile"

    def test_init_idempotent(self, reset_config):
        """Test that calling init multiple times doesn't cause issues."""
        with patch.object(Config, "_load_env") as mock_env:
            with patch.object(Config, "_load_all_settings"):
                with patch.object(Config, "_ensure_dirs_exist"):
                    init_config("test_profile")
                    call_count_1 = mock_env.call_count
                    init_config("test_profile")
                    call_count_2 = mock_env.call_count
                    assert call_count_1 == call_count_2

    def test_load_env_from_file(self, reset_config, temp_env_file):
        """Test loading environment variables from file."""
        # Load the env file using python-dotenv directly
        from dotenv import load_dotenv

        load_dotenv(Path.cwd() / temp_env_file)

        assert os.getenv("DEBUG_MODE") == "true"
        assert os.getenv("OPENAI_API_KEY") == "test-api-key"
        assert os.getenv("CHAT_MODEL") == "gpt-4-test"

    def test_load_env_nonexistent_file(self, reset_config):
        """Test loading nonexistent env file doesn't crash."""
        Config._load_env("nonexistent.env")

    def test_get_str_default(self):
        """Test _get_str returns default when not set."""
        result = Config._get_str("NONEXISTENT_VAR", "default_value")
        assert result == "default_value"

    def test_get_str_from_env(self, reset_config):
        """Test _get_str returns env value when set."""
        os.environ["TEST_VAR"] = "test_value"
        result = Config._get_str("TEST_VAR", "default_value")
        assert result == "test_value"
        del os.environ["TEST_VAR"]

    def test_get_int_default(self):
        """Test _get_int returns default when not set."""
        result = Config._get_int("NONEXISTENT_VAR", 42)
        assert result == 42

    def test_get_int_from_env(self, reset_config):
        """Test _get_int returns env value when set."""
        os.environ["TEST_VAR"] = "123"
        result = Config._get_int("TEST_VAR", 42)
        assert result == 123
        del os.environ["TEST_VAR"]

    def test_get_int_invalid_value(self, reset_config):
        """Test _get_int returns default for invalid value."""
        os.environ["TEST_VAR"] = "not_a_number"
        result = Config._get_int("TEST_VAR", 42)
        assert result == 42
        del os.environ["TEST_VAR"]

    def test_get_bool_default(self):
        """Test _get_bool returns default when not set."""
        result = Config._get_bool("NONEXISTENT_VAR", False)
        assert result is False

    def test_get_bool_true_values(self, reset_config):
        """Test _get_bool recognizes true values."""
        true_values = ["true", "TRUE", "1", "yes", "YES"]
        for i, val in enumerate(true_values):
            env_var = f"TEST_VAR_{i}"
            os.environ[env_var] = val
            result = Config._get_bool(env_var, False)
            assert result is True
            del os.environ[env_var]

    def test_get_bool_false_values(self, reset_config):
        """Test _get_bool recognizes false values."""
        false_values = ["false", "FALSE", "0", "no", "NO", "random"]
        for i, val in enumerate(false_values):
            env_var = f"TEST_VAR_{i}"
            os.environ[env_var] = val
            result = Config._get_bool(env_var, True)
            assert result is False
            del os.environ[env_var]

    def test_load_all_settings_debug(self, reset_config):
        """Test loading debug settings from env."""
        Config._profile = "test"
        os.environ["DEBUG_MODE"] = "true"
        os.environ["DEBUG_LOG_LEVEL"] = "DEBUG"
        os.environ["DEBUG_SHOW_FULL_PROMPT"] = "1"
        os.environ["DEBUG_LOG_DATABASE_OPS"] = "true"

        Config._load_all_settings()

        assert Config.DEBUG_MODE is True
        assert Config.DEBUG_LOG_LEVEL == "DEBUG"
        assert Config.DEBUG_SHOW_FULL_PROMPT is True
        assert Config.DEBUG_LOG_DATABASE_OPS is True

        for key in [
            "DEBUG_MODE",
            "DEBUG_LOG_LEVEL",
            "DEBUG_SHOW_FULL_PROMPT",
            "DEBUG_LOG_DATABASE_OPS",
        ]:
            if key in os.environ:
                del os.environ[key]

    def test_load_all_settings_timezone(self, reset_config):
        """Test loading timezone setting."""
        Config._profile = "test"
        os.environ["TIMEZONE"] = "UTC"
        Config._load_all_settings()
        assert Config.TIMEZONE_STR == "UTC"
        del os.environ["TIMEZONE"]

    def test_load_all_settings_context_window(self, reset_config):
        """Test loading context window settings."""
        Config._profile = "test"
        os.environ["CONTEXT_WINDOW_KEEP_MIN"] = "15"
        os.environ["CONTEXT_WINDOW_TRIGGER_SUMMARY"] = "30"
        os.environ["RECENT_SUMMARIES_MAX"] = "8"

        Config._load_all_settings()

        assert Config.CONTEXT_WINDOW_KEEP_MIN == 15
        assert Config.CONTEXT_WINDOW_TRIGGER_SUMMARY == 30
        assert Config.RECENT_SUMMARIES_MAX == 8

        for key in [
            "CONTEXT_WINDOW_KEEP_MIN",
            "CONTEXT_WINDOW_TRIGGER_SUMMARY",
            "RECENT_SUMMARIES_MAX",
        ]:
            if key in os.environ:
                del os.environ[key]

    def test_load_all_settings_retrieval(self, reset_config):
        """Test loading retrieval settings."""
        Config._profile = "test"
        os.environ["RECALL_SUMMARY_PER_QUERY"] = "5"
        os.environ["RECALL_CONV_PER_SUMMARY"] = "8"
        os.environ["RERANK_TOP_SUMMARIES"] = "4"
        os.environ["RERANK_TOP_CONVS"] = "12"

        Config._load_all_settings()

        assert Config.RECALL_SUMMARY_PER_QUERY == 5
        assert Config.RECALL_CONV_PER_SUMMARY == 8
        assert Config.RERANK_TOP_SUMMARIES == 4
        assert Config.RERANK_TOP_CONVS == 12

        for key in [
            "RECALL_SUMMARY_PER_QUERY",
            "RECALL_CONV_PER_SUMMARY",
            "RERANK_TOP_SUMMARIES",
            "RERANK_TOP_CONVS",
        ]:
            if key in os.environ:
                del os.environ[key]

    def test_load_all_settings_openai(self, reset_config):
        """Test loading OpenAI settings."""
        Config._profile = "test"
        os.environ["OPENAI_API_KEY"] = "test-key"
        os.environ["OPENAI_API_BASE"] = "https://custom.api.com/v1"
        os.environ["CHAT_MODEL"] = "gpt-4-custom"
        os.environ["TOOL_MODEL"] = "gpt-4-tooling"

        Config._load_all_settings()

        assert Config.OPENAI_API_KEY == "test-key"
        assert Config.OPENAI_API_BASE == "https://custom.api.com/v1"
        assert Config.CHAT_MODEL == "gpt-4-custom"
        assert Config.TOOL_MODEL == "gpt-4-tooling"

        for key in ["OPENAI_API_KEY", "OPENAI_API_BASE", "CHAT_MODEL", "TOOL_MODEL"]:
            if key in os.environ:
                del os.environ[key]

    def test_load_all_settings_embedding_defaults_to_openai(self, reset_config):
        """Test embedding settings default to OpenAI values if not specified."""
        Config._profile = "test"
        os.environ["OPENAI_API_KEY"] = "openai-key"
        os.environ["OPENAI_API_BASE"] = "https://openai.api.com/v1"

        Config._load_all_settings()

        assert Config.EMBEDDING_API_KEY == "openai-key"
        assert Config.EMBEDDING_API_BASE == "https://openai.api.com/v1"

        for key in ["OPENAI_API_KEY", "OPENAI_API_BASE"]:
            if key in os.environ:
                del os.environ[key]

    def test_load_all_settings_embedding_override(self, reset_config):
        """Test embedding settings can be overridden."""
        Config._profile = "test"
        os.environ["OPENAI_API_KEY"] = "openai-key"
        os.environ["OPENAI_API_BASE"] = "https://openai.api.com/v1"
        os.environ["EMBEDDING_API_KEY"] = "embedding-key"
        os.environ["EMBEDDING_API_BASE"] = "https://embedding.api.com/v1"
        os.environ["EMBEDDING_MODEL"] = "custom-embedding"
        os.environ["EMBEDDING_DIMENSION"] = "512"

        Config._load_all_settings()

        assert Config.EMBEDDING_API_KEY == "embedding-key"
        assert Config.EMBEDDING_API_BASE == "https://embedding.api.com/v1"
        assert Config.EMBEDDING_MODEL == "custom-embedding"
        assert Config.EMBEDDING_DIMENSION == 512

        for key in [
            "OPENAI_API_KEY",
            "OPENAI_API_BASE",
            "EMBEDDING_API_KEY",
            "EMBEDDING_API_BASE",
            "EMBEDDING_MODEL",
            "EMBEDDING_DIMENSION",
        ]:
            if key in os.environ:
                del os.environ[key]

    def test_load_all_settings_commands(self, reset_config):
        """Test loading command settings."""
        Config._profile = "test"
        os.environ["NEW_SESSION_COMMAND"] = "/startnew"
        os.environ["RESET_SESSION_COMMAND"] = "/clear"

        Config._load_all_settings()

        assert Config.NEW_SESSION_COMMAND == "/startnew"
        assert Config.RESET_SESSION_COMMAND == "/clear"

        for key in ["NEW_SESSION_COMMAND", "RESET_SESSION_COMMAND"]:
            if key in os.environ:
                del os.environ[key]

    def test_load_all_settings_telegram(self, reset_config):
        """Test loading Telegram settings."""
        Config._profile = "test"
        os.environ["TELEGRAM_BOT_TOKEN"] = "telegram-token"
        os.environ["TELEGRAM_USER_ID"] = "777888"
        os.environ["TELEGRAM_USE_MARKDOWN"] = "false"

        Config._load_all_settings()

        assert Config.TELEGRAM_BOT_TOKEN == "telegram-token"
        assert Config.TELEGRAM_USER_ID == 777888
        assert Config.TELEGRAM_USE_MARKDOWN is False

        for key in ["TELEGRAM_BOT_TOKEN", "TELEGRAM_USER_ID", "TELEGRAM_USE_MARKDOWN"]:
            if key in os.environ:
                del os.environ[key]

    def test_load_all_settings_skills_mcp(self, reset_config):
        """Test loading skills and MCP settings."""
        Config._profile = "test"
        os.environ["ENABLE_SKILLS"] = "false"
        os.environ["ENABLE_MCP"] = "true"
        os.environ["ENABLE_WEB_SEARCH"] = "true"
        os.environ["JINA_API_KEY"] = "jina-key"

        Config._load_all_settings()

        assert Config.ENABLE_SKILLS is False
        assert Config.ENABLE_MCP is True
        assert Config.ENABLE_WEB_SEARCH is True
        assert Config.JINA_API_KEY == "jina-key"

        for key in ["ENABLE_SKILLS", "ENABLE_MCP", "ENABLE_WEB_SEARCH", "JINA_API_KEY"]:
            if key in os.environ:
                del os.environ[key]

    def test_ensure_dirs_exist(self, reset_config, tmp_path):
        """Test _ensure_dirs_exist creates directory."""
        test_dir = tmp_path / "test_subdir"
        Config.DATA_DIR = test_dir
        Config._ensure_dirs_exist()
        assert test_dir.exists()


class TestInitConfig:
    """Test init_config convenience function."""

    def test_init_config_sets_profile(self, reset_config):
        """Test init_config properly initializes with profile."""
        with patch.object(Config, "init") as mock_init:
            init_config("test_profile")
            mock_init.assert_called_once_with("test_profile")
