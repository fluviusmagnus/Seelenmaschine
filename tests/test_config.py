import pytest
import os
from pathlib import Path
from unittest.mock import patch

from core.config import CONFIGURABLE_DEFAULTS, PROJECT_CONSTANTS, Config, init_config


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
        f.write("TELEGRAM_BOT_TOKEN=test-token\n")
        f.write("TELEGRAM_USER_ID=999999\n")
        f.write("ENABLE_MCP=true\n")
    yield filename
    if temp_path.exists():
        temp_path.unlink()


class TestConfig:
    """Test Config class functionality."""

    def test_config_defaults_before_init(self, reset_config):
        """Test default values before initialization."""
        assert Config.PROFILE == "default"
        assert Config.DATA_DIR == Path.cwd() / "data" / "default"
        assert Config.WORKSPACE_DIR == Path.cwd() / "data" / "default" / "workspace"
        assert (
            Config.MEDIA_DIR == Path.cwd() / "data" / "default" / "workspace" / "media"
        )
        assert Config.DEBUG_MODE is False
        assert Config.DEBUG_LOG_LEVEL == ""
        assert Config.TIMEZONE_STR == "Asia/Shanghai"
        assert Config.CHAT_MODEL == "gpt-4o"
        assert Config.TOOL_MODEL == "gpt-4o"
        assert Config.EMBEDDING_DIMENSION == 1536
        assert Config.EMBEDDING_CACHE_MAX_ENTRIES == 2048

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

    def test_embedding_cache_size_is_project_constant(self, reset_config):
        """Test embedding cache size is not loaded from env."""
        Config._profile = "test"
        os.environ["EMBEDDING_CACHE_MAX_ENTRIES"] = "128"

        Config._load_all_settings()

        assert Config.EMBEDDING_CACHE_MAX_ENTRIES == PROJECT_CONSTANTS[
            "EMBEDDING_CACHE_MAX_ENTRIES"
        ]

        del os.environ["EMBEDDING_CACHE_MAX_ENTRIES"]

    def test_command_settings_are_project_constants(self, reset_config):
        """Test command settings are not loaded from env."""
        Config._profile = "test"
        os.environ["NEW_SESSION_COMMAND"] = "/startnew"
        os.environ["RESET_SESSION_COMMAND"] = "/clear"

        Config._load_all_settings()

        assert Config.NEW_SESSION_COMMAND == PROJECT_CONSTANTS["NEW_SESSION_COMMAND"]
        assert Config.RESET_SESSION_COMMAND == PROJECT_CONSTANTS["RESET_SESSION_COMMAND"]

        for key in ["NEW_SESSION_COMMAND", "RESET_SESSION_COMMAND"]:
            if key in os.environ:
                del os.environ[key]

    def test_load_all_settings_telegram(self, reset_config):
        """Test loading Telegram settings."""
        Config._profile = "test"
        os.environ["TELEGRAM_BOT_TOKEN"] = "telegram-token"
        os.environ["TELEGRAM_USER_ID"] = "777888"

        Config._load_all_settings()

        assert Config.TELEGRAM_BOT_TOKEN == "telegram-token"
        assert Config.TELEGRAM_USER_ID == 777888

        for key in ["TELEGRAM_BOT_TOKEN", "TELEGRAM_USER_ID"]:
            if key in os.environ:
                del os.environ[key]

    def test_telegram_adapter_settings_are_project_constants(self, reset_config):
        """Test Telegram adapter internals are not loaded from env."""
        Config._profile = "test"
        os.environ["TELEGRAM_USE_MARKDOWN"] = "false"
        os.environ["TELEGRAM_CONNECT_TIMEOUT"] = "99.0"
        os.environ["TELEGRAM_BOOTSTRAP_RETRIES"] = "99"

        Config._load_all_settings()

        assert Config.TELEGRAM_USE_MARKDOWN is PROJECT_CONSTANTS[
            "TELEGRAM_USE_MARKDOWN"
        ]
        assert Config.TELEGRAM_CONNECT_TIMEOUT == PROJECT_CONSTANTS[
            "TELEGRAM_CONNECT_TIMEOUT"
        ]
        assert Config.TELEGRAM_BOOTSTRAP_RETRIES == PROJECT_CONSTANTS[
            "TELEGRAM_BOOTSTRAP_RETRIES"
        ]

        for key in [
            "TELEGRAM_USE_MARKDOWN",
            "TELEGRAM_CONNECT_TIMEOUT",
            "TELEGRAM_BOOTSTRAP_RETRIES",
        ]:
            if key in os.environ:
                del os.environ[key]

    def test_load_all_settings_media_dir_default(self, reset_config):
        """Test WORKSPACE_DIR and MEDIA_DIR default locations."""
        Config._profile = "test_profile"

        if "WORKSPACE_DIR" in os.environ:
            del os.environ["WORKSPACE_DIR"]
        if "MEDIA_DIR" in os.environ:
            del os.environ["MEDIA_DIR"]

        Config._load_all_settings()

        assert (
            Config.WORKSPACE_DIR == Path.cwd() / "data" / "test_profile" / "workspace"
        )
        assert (
            Config.MEDIA_DIR
            == Path.cwd() / "data" / "test_profile" / "workspace" / "media"
        )

    def test_load_all_settings_workspace_dir_override(self, reset_config):
        """Test WORKSPACE_DIR can be overridden by environment."""
        Config._profile = "test"
        os.environ["WORKSPACE_DIR"] = "custom_workspace"

        Config._load_all_settings()

        assert Config.WORKSPACE_DIR == Path.cwd() / "custom_workspace"
        assert Config.MEDIA_DIR == Path.cwd() / "custom_workspace" / "media"

        del os.environ["WORKSPACE_DIR"]

    def test_load_all_settings_media_dir_override(self, reset_config):
        """Test MEDIA_DIR can be overridden by environment."""
        Config._profile = "test"
        os.environ["MEDIA_DIR"] = "custom_media"

        Config._load_all_settings()

        assert Config.MEDIA_DIR == Path.cwd() / "custom_media"

        del os.environ["MEDIA_DIR"]

    def test_load_all_settings_mcp(self, reset_config):
        """Test loading MCP settings."""
        Config._profile = "test"
        os.environ["ENABLE_MCP"] = "true"

        Config._load_all_settings()

        assert Config.ENABLE_MCP is True

        for key in ["ENABLE_MCP"]:
            if key in os.environ:
                del os.environ[key]

    def test_configurable_setting_can_be_overridden(self, reset_config):
        """Test profile-configurable settings can be overridden by env."""
        Config._profile = "test"
        os.environ["TOOL_LOOP_MAX_ITERATIONS"] = "17"

        Config._load_all_settings()

        assert Config.TOOL_LOOP_MAX_ITERATIONS == 17

        del os.environ["TOOL_LOOP_MAX_ITERATIONS"]

    def test_project_constant_ignores_env_override(self, reset_config):
        """Test project constants are not loaded from profile env."""
        Config._profile = "test"
        os.environ["SHELL_OUTPUT_MAX_CHARS"] = "999"

        Config._load_all_settings()

        assert Config.SHELL_OUTPUT_MAX_CHARS == PROJECT_CONSTANTS[
            "SHELL_OUTPUT_MAX_CHARS"
        ]

        del os.environ["SHELL_OUTPUT_MAX_CHARS"]

    def test_env_example_lists_configurable_defaults_only(self):
        """Test .env.example documents configurable keys, not constants."""
        env_example = Path(".env.example").read_text(encoding="utf-8")
        documented_keys = {
            line.split("=", 1)[0]
            for line in env_example.splitlines()
            if line and not line.startswith("#") and "=" in line
        }

        assert set(CONFIGURABLE_DEFAULTS) <= documented_keys
        assert set(PROJECT_CONSTANTS).isdisjoint(documented_keys)

    def test_ensure_dirs_exist(self, reset_config, tmp_path):
        """Test _ensure_dirs_exist creates directory."""
        test_dir = tmp_path / "test_subdir"
        workspace_dir = tmp_path / "workspace"
        media_dir = tmp_path / "test_media"
        Config.DATA_DIR = test_dir
        Config.WORKSPACE_DIR = workspace_dir
        Config.MEDIA_DIR = media_dir
        Config._ensure_dirs_exist()
        assert test_dir.exists()
        assert workspace_dir.exists()
        assert media_dir.exists()


class TestInitConfig:
    """Test init_config convenience function."""

    def test_init_config_sets_profile(self, reset_config):
        """Test init_config properly initializes with profile."""
        with patch.object(Config, "init") as mock_init:
            init_config("test_profile")
            mock_init.assert_called_once_with("test_profile")


class TestLoggerLevelResolution:
    """Test effective logger level resolution from debug settings."""

    def test_debug_mode_defaults_to_debug_level(self, reset_config):
        from utils.logger import _resolve_log_level

        Config.DEBUG_MODE = True
        Config.DEBUG_LOG_LEVEL = ""

        assert _resolve_log_level() == "DEBUG"

    def test_non_debug_mode_defaults_to_info_level(self, reset_config):
        from utils.logger import _resolve_log_level

        Config.DEBUG_MODE = False
        Config.DEBUG_LOG_LEVEL = ""

        assert _resolve_log_level() == "INFO"

    def test_explicit_log_level_overrides_debug_mode(self, reset_config):
        from utils.logger import _resolve_log_level

        Config.DEBUG_MODE = False
        Config.DEBUG_LOG_LEVEL = "warning"

        assert _resolve_log_level() == "WARNING"
