import os
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo
from threading import Lock


DEFAULT_PROFILE = "default"

# These keys are the settings intentionally supported by profile .env files.
CONFIGURABLE_DEFAULTS: dict[str, Any] = {
    "WORKSPACE_DIR": "",
    "MEDIA_DIR": "",
    "DEBUG_MODE": False,
    "DEBUG_LOG_LEVEL": "",
    "DEBUG_SHOW_FULL_PROMPT": False,
    "DEBUG_LOG_DATABASE_OPS": False,
    "TIMEZONE": "Asia/Shanghai",
    "CONTEXT_WINDOW_KEEP_MIN": 12,
    "CONTEXT_WINDOW_TRIGGER_SUMMARY": 24,
    "RECENT_SUMMARIES_MAX": 3,
    "TOOL_EXECUTION_TIMEOUT_SECONDS": 90.0,
    "TOOL_LOOP_MAX_ITERATIONS": 30,
    "RECALL_SUMMARY_PER_QUERY": 3,
    "RECALL_CONV_PER_SUMMARY": 4,
    "RERANK_TOP_SUMMARIES": 3,
    "RERANK_TOP_CONVS": 6,
    "OPENAI_API_KEY": "",
    "OPENAI_API_BASE": "https://api.openai.com/v1",
    "CHAT_MODEL": "gpt-4o",
    "TOOL_MODEL": "gpt-4o",
    "CHAT_REASONING_EFFORT": "low",
    "TOOL_REASONING_EFFORT": "medium",
    "EMBEDDING_API_KEY": "",
    "EMBEDDING_API_BASE": "",
    "EMBEDDING_MODEL": "text-embedding-3-small",
    "EMBEDDING_DIMENSION": 1536,
    "RERANK_API_KEY": "",
    "RERANK_MODEL": "",
    "RERANK_API_BASE": "",
    "TELEGRAM_BOT_TOKEN": "",
    "TELEGRAM_USER_ID": 0,
    "ENABLE_MCP": False,
    "MCP_CONFIG_PATH": "mcp_servers.json",
}

# Internal project constants. They are exposed on Config for existing callers,
# but profile .env files do not override them.
PROJECT_CONSTANTS: dict[str, Any] = {
    "TOOL_LLM_MAX_RESPONSE_CHARS": 12000,
    "TOOL_LLM_TRUNCATE_HEAD_CHARS": 6000,
    "TOOL_LLM_TRUNCATE_TAIL_CHARS": 4000,
    "MCP_TEXT_BLOCK_MAX_CHARS": 12000,
    "MCP_TEXT_BLOCK_TRUNCATE_HEAD_CHARS": 6000,
    "MCP_TEXT_BLOCK_TRUNCATE_TAIL_CHARS": 4000,
    "TOOL_TRACE_ARGUMENTS_PREVIEW_MAX": 300,
    "TOOL_TRACE_ARGUMENTS_FULL_MAX": 1000,
    "TOOL_TRACE_RESULT_PREVIEW_MAX": 1000,
    "TOOL_TRACE_RESULT_FULL_MAX": 12000,
    "TOOL_EXECUTION_NOTIFICATION_ARGUMENTS_MAX": 500,
    "TELEGRAM_MESSAGE_MAX_LENGTH": 4000,
    "SHELL_OUTPUT_MAX_CHARS": 12000,
    "SHELL_OUTPUT_HEAD_CHARS": 6000,
    "SHELL_OUTPUT_TAIL_CHARS": 4000,
    "READ_FILE_TEXT_MAX_CHARS": 12000,
    "EMBEDDING_CACHE_MAX_ENTRIES": 2048,
    "TELEGRAM_USE_MARKDOWN": True,
    "TELEGRAM_CONNECT_TIMEOUT": 15.0,
    "TELEGRAM_READ_TIMEOUT": 30.0,
    "TELEGRAM_WRITE_TIMEOUT": 30.0,
    "TELEGRAM_POOL_TIMEOUT": 15.0,
    "TELEGRAM_GET_UPDATES_CONNECT_TIMEOUT": 5.0,
    "TELEGRAM_GET_UPDATES_READ_TIMEOUT": 5.0,
    "TELEGRAM_GET_UPDATES_WRITE_TIMEOUT": 5.0,
    "TELEGRAM_GET_UPDATES_POOL_TIMEOUT": 5.0,
    "TELEGRAM_BOOTSTRAP_RETRIES": 3,
    "NEW_SESSION_COMMAND": "/new",
    "RESET_SESSION_COMMAND": "/reset",
}


class Config:
    """Configuration class with class-level access support"""

    _initialized: bool = False
    _profile: Optional[str] = None
    _lock: Lock = Lock()

    # Will be set during initialization
    PROFILE: str = DEFAULT_PROFILE
    DATA_DIR: Path = Path.cwd() / "data" / DEFAULT_PROFILE
    DB_PATH: Path = Path.cwd() / "data" / DEFAULT_PROFILE / "chatbot.db"
    SEELE_JSON_PATH: Path = Path.cwd() / "data" / DEFAULT_PROFILE / "seele.json"
    WORKSPACE_DIR: Path = Path.cwd() / "data" / DEFAULT_PROFILE / "workspace"
    MEDIA_DIR: Path = Path.cwd() / "data" / DEFAULT_PROFILE / "workspace" / "media"

    # Debug settings
    DEBUG_MODE: bool = CONFIGURABLE_DEFAULTS["DEBUG_MODE"]
    DEBUG_LOG_LEVEL: str = CONFIGURABLE_DEFAULTS["DEBUG_LOG_LEVEL"]
    DEBUG_SHOW_FULL_PROMPT: bool = CONFIGURABLE_DEFAULTS["DEBUG_SHOW_FULL_PROMPT"]
    DEBUG_LOG_DATABASE_OPS: bool = CONFIGURABLE_DEFAULTS["DEBUG_LOG_DATABASE_OPS"]

    # Timezone
    TIMEZONE: ZoneInfo = ZoneInfo(CONFIGURABLE_DEFAULTS["TIMEZONE"])
    TIMEZONE_STR: str = CONFIGURABLE_DEFAULTS["TIMEZONE"]

    # Context window settings
    CONTEXT_WINDOW_KEEP_MIN: int = CONFIGURABLE_DEFAULTS["CONTEXT_WINDOW_KEEP_MIN"]
    CONTEXT_WINDOW_TRIGGER_SUMMARY: int = CONFIGURABLE_DEFAULTS[
        "CONTEXT_WINDOW_TRIGGER_SUMMARY"
    ]
    RECENT_SUMMARIES_MAX: int = CONFIGURABLE_DEFAULTS["RECENT_SUMMARIES_MAX"]

    # Tool execution settings
    TOOL_EXECUTION_TIMEOUT_SECONDS: float = CONFIGURABLE_DEFAULTS[
        "TOOL_EXECUTION_TIMEOUT_SECONDS"
    ]
    TOOL_LOOP_MAX_ITERATIONS: int = CONFIGURABLE_DEFAULTS["TOOL_LOOP_MAX_ITERATIONS"]

    # Project constants exposed through Config for existing callers
    TOOL_LLM_MAX_RESPONSE_CHARS: int = PROJECT_CONSTANTS["TOOL_LLM_MAX_RESPONSE_CHARS"]
    TOOL_LLM_TRUNCATE_HEAD_CHARS: int = PROJECT_CONSTANTS[
        "TOOL_LLM_TRUNCATE_HEAD_CHARS"
    ]
    TOOL_LLM_TRUNCATE_TAIL_CHARS: int = PROJECT_CONSTANTS[
        "TOOL_LLM_TRUNCATE_TAIL_CHARS"
    ]
    MCP_TEXT_BLOCK_MAX_CHARS: int = PROJECT_CONSTANTS["MCP_TEXT_BLOCK_MAX_CHARS"]
    MCP_TEXT_BLOCK_TRUNCATE_HEAD_CHARS: int = PROJECT_CONSTANTS[
        "MCP_TEXT_BLOCK_TRUNCATE_HEAD_CHARS"
    ]
    MCP_TEXT_BLOCK_TRUNCATE_TAIL_CHARS: int = PROJECT_CONSTANTS[
        "MCP_TEXT_BLOCK_TRUNCATE_TAIL_CHARS"
    ]
    TOOL_TRACE_ARGUMENTS_PREVIEW_MAX: int = PROJECT_CONSTANTS[
        "TOOL_TRACE_ARGUMENTS_PREVIEW_MAX"
    ]
    TOOL_TRACE_ARGUMENTS_FULL_MAX: int = PROJECT_CONSTANTS[
        "TOOL_TRACE_ARGUMENTS_FULL_MAX"
    ]
    TOOL_TRACE_RESULT_PREVIEW_MAX: int = PROJECT_CONSTANTS[
        "TOOL_TRACE_RESULT_PREVIEW_MAX"
    ]
    TOOL_TRACE_RESULT_FULL_MAX: int = PROJECT_CONSTANTS["TOOL_TRACE_RESULT_FULL_MAX"]
    TOOL_EXECUTION_NOTIFICATION_ARGUMENTS_MAX: int = PROJECT_CONSTANTS[
        "TOOL_EXECUTION_NOTIFICATION_ARGUMENTS_MAX"
    ]
    TELEGRAM_MESSAGE_MAX_LENGTH: int = PROJECT_CONSTANTS["TELEGRAM_MESSAGE_MAX_LENGTH"]
    SHELL_OUTPUT_MAX_CHARS: int = PROJECT_CONSTANTS["SHELL_OUTPUT_MAX_CHARS"]
    SHELL_OUTPUT_HEAD_CHARS: int = PROJECT_CONSTANTS["SHELL_OUTPUT_HEAD_CHARS"]
    SHELL_OUTPUT_TAIL_CHARS: int = PROJECT_CONSTANTS["SHELL_OUTPUT_TAIL_CHARS"]
    READ_FILE_TEXT_MAX_CHARS: int = PROJECT_CONSTANTS["READ_FILE_TEXT_MAX_CHARS"]

    # Retrieval settings
    RECALL_SUMMARY_PER_QUERY: int = CONFIGURABLE_DEFAULTS["RECALL_SUMMARY_PER_QUERY"]
    RECALL_CONV_PER_SUMMARY: int = CONFIGURABLE_DEFAULTS["RECALL_CONV_PER_SUMMARY"]
    RERANK_TOP_SUMMARIES: int = CONFIGURABLE_DEFAULTS["RERANK_TOP_SUMMARIES"]
    RERANK_TOP_CONVS: int = CONFIGURABLE_DEFAULTS["RERANK_TOP_CONVS"]

    # OpenAI settings
    OPENAI_API_KEY: str = CONFIGURABLE_DEFAULTS["OPENAI_API_KEY"]
    OPENAI_API_BASE: str = CONFIGURABLE_DEFAULTS["OPENAI_API_BASE"]
    CHAT_MODEL: str = CONFIGURABLE_DEFAULTS["CHAT_MODEL"]
    TOOL_MODEL: str = CONFIGURABLE_DEFAULTS["TOOL_MODEL"]
    CHAT_REASONING_EFFORT: str = CONFIGURABLE_DEFAULTS["CHAT_REASONING_EFFORT"]
    TOOL_REASONING_EFFORT: str = CONFIGURABLE_DEFAULTS["TOOL_REASONING_EFFORT"]

    # Embedding settings
    EMBEDDING_API_KEY: str = CONFIGURABLE_DEFAULTS["EMBEDDING_API_KEY"]
    EMBEDDING_API_BASE: str = CONFIGURABLE_DEFAULTS["OPENAI_API_BASE"]
    EMBEDDING_MODEL: str = CONFIGURABLE_DEFAULTS["EMBEDDING_MODEL"]
    EMBEDDING_DIMENSION: int = CONFIGURABLE_DEFAULTS["EMBEDDING_DIMENSION"]
    EMBEDDING_CACHE_MAX_ENTRIES: int = PROJECT_CONSTANTS["EMBEDDING_CACHE_MAX_ENTRIES"]

    # Reranker settings
    RERANK_API_KEY: str = CONFIGURABLE_DEFAULTS["RERANK_API_KEY"]
    RERANK_MODEL: str = CONFIGURABLE_DEFAULTS["RERANK_MODEL"]
    RERANK_API_BASE: str = CONFIGURABLE_DEFAULTS["RERANK_API_BASE"]

    # Telegram settings
    TELEGRAM_BOT_TOKEN: str = CONFIGURABLE_DEFAULTS["TELEGRAM_BOT_TOKEN"]
    TELEGRAM_USER_ID: int = CONFIGURABLE_DEFAULTS["TELEGRAM_USER_ID"]
    TELEGRAM_USE_MARKDOWN: bool = PROJECT_CONSTANTS["TELEGRAM_USE_MARKDOWN"]
    TELEGRAM_CONNECT_TIMEOUT: float = PROJECT_CONSTANTS["TELEGRAM_CONNECT_TIMEOUT"]
    TELEGRAM_READ_TIMEOUT: float = PROJECT_CONSTANTS["TELEGRAM_READ_TIMEOUT"]
    TELEGRAM_WRITE_TIMEOUT: float = PROJECT_CONSTANTS["TELEGRAM_WRITE_TIMEOUT"]
    TELEGRAM_POOL_TIMEOUT: float = PROJECT_CONSTANTS["TELEGRAM_POOL_TIMEOUT"]
    TELEGRAM_GET_UPDATES_CONNECT_TIMEOUT: float = PROJECT_CONSTANTS[
        "TELEGRAM_GET_UPDATES_CONNECT_TIMEOUT"
    ]
    TELEGRAM_GET_UPDATES_READ_TIMEOUT: float = PROJECT_CONSTANTS[
        "TELEGRAM_GET_UPDATES_READ_TIMEOUT"
    ]
    TELEGRAM_GET_UPDATES_WRITE_TIMEOUT: float = PROJECT_CONSTANTS[
        "TELEGRAM_GET_UPDATES_WRITE_TIMEOUT"
    ]
    TELEGRAM_GET_UPDATES_POOL_TIMEOUT: float = PROJECT_CONSTANTS[
        "TELEGRAM_GET_UPDATES_POOL_TIMEOUT"
    ]
    TELEGRAM_BOOTSTRAP_RETRIES: int = PROJECT_CONSTANTS["TELEGRAM_BOOTSTRAP_RETRIES"]
    NEW_SESSION_COMMAND: str = PROJECT_CONSTANTS["NEW_SESSION_COMMAND"]
    RESET_SESSION_COMMAND: str = PROJECT_CONSTANTS["RESET_SESSION_COMMAND"]

    # MCP settings
    ENABLE_MCP: bool = CONFIGURABLE_DEFAULTS["ENABLE_MCP"]
    MCP_CONFIG_PATH: Path = Path.cwd() / CONFIGURABLE_DEFAULTS["MCP_CONFIG_PATH"]

    @classmethod
    def init(cls, profile: str) -> None:
        """Initialize configuration from environment file.

        Thread-safe initialization using a lock to prevent race conditions
        in multi-threaded or async environments.
        """
        with cls._lock:
            if cls._initialized:
                return

            cls._profile = profile
            cls.PROFILE = profile
            cls._load_env(profile)
            cls._load_all_settings()
            cls._ensure_dirs_exist()
            cls._initialized = True

    @classmethod
    def _load_env(cls, profile: str) -> None:
        """Load environment variables from profile .env file"""
        env_file = Path.cwd() / f"{profile}.env"

        if env_file.exists():
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        os.environ[key.strip()] = value.strip()

    @classmethod
    def _load_all_settings(cls) -> None:
        """Load all settings from environment variables"""
        # Data directory
        profile = cls._profile if cls._profile is not None else DEFAULT_PROFILE
        cls.DATA_DIR = Path.cwd() / "data" / profile
        cls.DB_PATH = cls.DATA_DIR / "chatbot.db"
        cls.SEELE_JSON_PATH = cls.DATA_DIR / "seele.json"
        workspace_dir_str = cls._get_str(
            "WORKSPACE_DIR", CONFIGURABLE_DEFAULTS["WORKSPACE_DIR"]
        )
        cls.WORKSPACE_DIR = (
            Path(workspace_dir_str) if workspace_dir_str else cls.DATA_DIR / "workspace"
        )
        if not cls.WORKSPACE_DIR.is_absolute():
            cls.WORKSPACE_DIR = Path.cwd() / cls.WORKSPACE_DIR

        media_dir_str = cls._get_str("MEDIA_DIR", CONFIGURABLE_DEFAULTS["MEDIA_DIR"])
        cls.MEDIA_DIR = (
            Path(media_dir_str) if media_dir_str else cls.WORKSPACE_DIR / "media"
        )
        if not cls.MEDIA_DIR.is_absolute():
            cls.MEDIA_DIR = Path.cwd() / cls.MEDIA_DIR

        # Debug settings
        cls.DEBUG_MODE = cls._get_bool(
            "DEBUG_MODE", CONFIGURABLE_DEFAULTS["DEBUG_MODE"]
        )
        cls.DEBUG_LOG_LEVEL = cls._get_str(
            "DEBUG_LOG_LEVEL", CONFIGURABLE_DEFAULTS["DEBUG_LOG_LEVEL"]
        )
        cls.DEBUG_SHOW_FULL_PROMPT = cls._get_bool(
            "DEBUG_SHOW_FULL_PROMPT", CONFIGURABLE_DEFAULTS["DEBUG_SHOW_FULL_PROMPT"]
        )
        cls.DEBUG_LOG_DATABASE_OPS = cls._get_bool(
            "DEBUG_LOG_DATABASE_OPS", CONFIGURABLE_DEFAULTS["DEBUG_LOG_DATABASE_OPS"]
        )

        # Timezone
        tz_str = cls._get_str("TIMEZONE", CONFIGURABLE_DEFAULTS["TIMEZONE"])
        cls.TIMEZONE = ZoneInfo(tz_str)
        cls.TIMEZONE_STR = tz_str

        # Context window settings
        cls.CONTEXT_WINDOW_KEEP_MIN = cls._get_int(
            "CONTEXT_WINDOW_KEEP_MIN", CONFIGURABLE_DEFAULTS["CONTEXT_WINDOW_KEEP_MIN"]
        )
        cls.CONTEXT_WINDOW_TRIGGER_SUMMARY = cls._get_int(
            "CONTEXT_WINDOW_TRIGGER_SUMMARY",
            CONFIGURABLE_DEFAULTS["CONTEXT_WINDOW_TRIGGER_SUMMARY"],
        )
        cls.RECENT_SUMMARIES_MAX = cls._get_int(
            "RECENT_SUMMARIES_MAX", CONFIGURABLE_DEFAULTS["RECENT_SUMMARIES_MAX"]
        )

        # Internal constants
        cls._load_project_constants()

        # Tool execution settings
        cls.TOOL_EXECUTION_TIMEOUT_SECONDS = cls._get_float(
            "TOOL_EXECUTION_TIMEOUT_SECONDS",
            CONFIGURABLE_DEFAULTS["TOOL_EXECUTION_TIMEOUT_SECONDS"],
        )
        cls.TOOL_LOOP_MAX_ITERATIONS = cls._get_int(
            "TOOL_LOOP_MAX_ITERATIONS",
            CONFIGURABLE_DEFAULTS["TOOL_LOOP_MAX_ITERATIONS"],
        )

        # Retrieval settings
        cls.RECALL_SUMMARY_PER_QUERY = cls._get_int(
            "RECALL_SUMMARY_PER_QUERY",
            CONFIGURABLE_DEFAULTS["RECALL_SUMMARY_PER_QUERY"],
        )
        cls.RECALL_CONV_PER_SUMMARY = cls._get_int(
            "RECALL_CONV_PER_SUMMARY",
            CONFIGURABLE_DEFAULTS["RECALL_CONV_PER_SUMMARY"],
        )
        cls.RERANK_TOP_SUMMARIES = cls._get_int(
            "RERANK_TOP_SUMMARIES", CONFIGURABLE_DEFAULTS["RERANK_TOP_SUMMARIES"]
        )
        cls.RERANK_TOP_CONVS = cls._get_int(
            "RERANK_TOP_CONVS", CONFIGURABLE_DEFAULTS["RERANK_TOP_CONVS"]
        )

        # OpenAI settings
        cls.OPENAI_API_KEY = cls._get_str(
            "OPENAI_API_KEY", CONFIGURABLE_DEFAULTS["OPENAI_API_KEY"]
        )
        cls.OPENAI_API_BASE = cls._get_str(
            "OPENAI_API_BASE", CONFIGURABLE_DEFAULTS["OPENAI_API_BASE"]
        )
        cls.CHAT_MODEL = cls._get_str(
            "CHAT_MODEL", CONFIGURABLE_DEFAULTS["CHAT_MODEL"]
        )
        cls.TOOL_MODEL = cls._get_str(
            "TOOL_MODEL", CONFIGURABLE_DEFAULTS["TOOL_MODEL"]
        )
        cls.CHAT_REASONING_EFFORT = cls._get_str(
            "CHAT_REASONING_EFFORT", CONFIGURABLE_DEFAULTS["CHAT_REASONING_EFFORT"]
        )
        cls.TOOL_REASONING_EFFORT = cls._get_str(
            "TOOL_REASONING_EFFORT", CONFIGURABLE_DEFAULTS["TOOL_REASONING_EFFORT"]
        )

        # Embedding settings (default to OpenAI settings if not specified)
        cls.EMBEDDING_API_KEY = cls._get_str(
            "EMBEDDING_API_KEY", cls.OPENAI_API_KEY
        )
        cls.EMBEDDING_API_BASE = cls._get_str(
            "EMBEDDING_API_BASE", cls.OPENAI_API_BASE
        )
        cls.EMBEDDING_MODEL = cls._get_str(
            "EMBEDDING_MODEL", CONFIGURABLE_DEFAULTS["EMBEDDING_MODEL"]
        )
        cls.EMBEDDING_DIMENSION = cls._get_int(
            "EMBEDDING_DIMENSION", CONFIGURABLE_DEFAULTS["EMBEDDING_DIMENSION"]
        )

        # Reranker settings
        cls.RERANK_API_KEY = cls._get_str(
            "RERANK_API_KEY", CONFIGURABLE_DEFAULTS["RERANK_API_KEY"]
        )
        cls.RERANK_MODEL = cls._get_str(
            "RERANK_MODEL", CONFIGURABLE_DEFAULTS["RERANK_MODEL"]
        )
        cls.RERANK_API_BASE = cls._get_str(
            "RERANK_API_BASE", CONFIGURABLE_DEFAULTS["RERANK_API_BASE"]
        )

        # Telegram settings
        cls.TELEGRAM_BOT_TOKEN = cls._get_str(
            "TELEGRAM_BOT_TOKEN", CONFIGURABLE_DEFAULTS["TELEGRAM_BOT_TOKEN"]
        )
        cls.TELEGRAM_USER_ID = cls._get_int(
            "TELEGRAM_USER_ID", CONFIGURABLE_DEFAULTS["TELEGRAM_USER_ID"]
        )

        # MCP settings
        cls.ENABLE_MCP = cls._get_bool(
            "ENABLE_MCP", CONFIGURABLE_DEFAULTS["ENABLE_MCP"]
        )
        mcp_config_path_str = (
            cls._get_str("MCP_CONFIG_PATH", CONFIGURABLE_DEFAULTS["MCP_CONFIG_PATH"])
            or CONFIGURABLE_DEFAULTS["MCP_CONFIG_PATH"]
        )
        cls.MCP_CONFIG_PATH = Path.cwd() / mcp_config_path_str

    @classmethod
    def _load_project_constants(cls) -> None:
        """Expose non-configurable project constants on Config."""
        for key, value in PROJECT_CONSTANTS.items():
            setattr(cls, key, value)

    @classmethod
    def _ensure_dirs_exist(cls) -> None:
        """Ensure required directories exist"""
        os.makedirs(cls.DATA_DIR, exist_ok=True)
        os.makedirs(cls.WORKSPACE_DIR, exist_ok=True)
        os.makedirs(cls.MEDIA_DIR, exist_ok=True)

    @staticmethod
    def _get_str(key: str, default: str = "") -> str:
        """Get string value from environment"""
        return os.getenv(key, default)

    @staticmethod
    def _get_int(key: str, default: int = 0) -> int:
        """Get integer value from environment"""
        value = os.getenv(key)
        return int(value) if value and value.isdigit() else default

    @staticmethod
    def _get_float(key: str, default: float = 0.0) -> float:
        """Get float value from environment."""
        value = os.getenv(key)
        if value is None or value == "":
            return default

        try:
            return float(value)
        except ValueError:
            return default

    @staticmethod
    def _get_bool(key: str, default: bool = False) -> bool:
        """Get boolean value from environment"""
        value = os.getenv(key)
        if value is None or value == "":
            return default
        value = value.lower()
        return value in ("true", "1", "yes")


def init_config(profile: str) -> None:
    """Initialize configuration (convenience function)"""
    Config.init(profile)
