import os
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo


class Config:
    """Configuration class with class-level access support"""
    _initialized: bool = False
    _profile: Optional[str] = None

    # Will be set during initialization
    PROFILE: str = "default"
    DATA_DIR: Path = Path.cwd() / "data" / "default"
    DB_PATH: Path = Path.cwd() / "data" / "default" / "chatbot.db"
    SEELE_JSON_PATH: Path = Path.cwd() / "data" / "default" / "seele.json"
    SCHEDULED_TASKS_PATH: Path = Path.cwd() / "data" / "default" / "scheduled_tasks.json"
    
    # Debug settings
    DEBUG_MODE: bool = False
    DEBUG_LOG_LEVEL: str = "INFO"
    DEBUG_SHOW_FULL_PROMPT: bool = False
    DEBUG_LOG_DATABASE_OPS: bool = False
    
    # Timezone
    TIMEZONE: ZoneInfo = ZoneInfo("Asia/Shanghai")
    TIMEZONE_STR: str = "Asia/Shanghai"
    
    # Context window settings
    CONTEXT_WINDOW_KEEP_MIN: int = 12
    CONTEXT_WINDOW_TRIGGER_SUMMARY: int = 24
    RECENT_SUMMARIES_MAX: int = 3
    
    # Retrieval settings
    RECALL_SUMMARY_PER_QUERY: int = 3
    RECALL_CONV_PER_SUMMARY: int = 4
    RERANK_TOP_SUMMARIES: int = 3
    RERANK_TOP_CONVS: int = 6
    
    # OpenAI settings
    OPENAI_API_KEY: str = ""
    OPENAI_API_BASE: str = "https://api.openai.com/v1"
    CHAT_MODEL: str = "gpt-4o"
    TOOL_MODEL: str = "gpt-4o"
    CHAT_REASONING_EFFORT: str = "low"
    TOOL_REASONING_EFFORT: str = "medium"
    
    # Embedding settings
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_API_BASE: str = "https://api.openai.com/v1"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSION: int = 1536
    
    # Command settings
    NEW_SESSION_COMMAND: str = "/new"
    RESET_SESSION_COMMAND: str = "/reset"
    
    # Reranker settings
    RERANK_API_KEY: str = ""
    RERANK_MODEL: str = ""
    RERANK_API_BASE: str = ""
    
    # Telegram settings
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_USER_ID: int = 0
    TELEGRAM_USE_MARKDOWN: bool = True
    
    # Skills settings
    ENABLE_SKILLS: bool = True
    SKILLS_DIR: str = "skills/"
    
    # MCP settings
    ENABLE_MCP: bool = False
    MCP_CONFIG_PATH: Path = Path.cwd() / "mcp_servers.json"
    
    # Web search settings
    ENABLE_WEB_SEARCH: bool = False
    JINA_API_KEY: str = ""

    @classmethod
    def init(cls, profile: str) -> None:
        """Initialize configuration from environment file"""
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
        cls.DATA_DIR = Path.cwd() / "data" / cls._profile
        cls.DB_PATH = cls.DATA_DIR / "chatbot.db"
        cls.SEELE_JSON_PATH = cls.DATA_DIR / "seele.json"
        cls.SCHEDULED_TASKS_PATH = cls.DATA_DIR / "scheduled_tasks.json"
        
        # Debug settings
        cls.DEBUG_MODE = cls._get_bool("DEBUG_MODE", False)
        cls.DEBUG_LOG_LEVEL = cls._get_str("DEBUG_LOG_LEVEL", "INFO")
        cls.DEBUG_SHOW_FULL_PROMPT = cls._get_bool("DEBUG_SHOW_FULL_PROMPT", False)
        cls.DEBUG_LOG_DATABASE_OPS = cls._get_bool("DEBUG_LOG_DATABASE_OPS", False)
        
        # Timezone
        tz_str = cls._get_str("TIMEZONE", "Asia/Shanghai")
        cls.TIMEZONE = ZoneInfo(tz_str)
        cls.TIMEZONE_STR = tz_str
        
        # Context window settings
        cls.CONTEXT_WINDOW_KEEP_MIN = cls._get_int("CONTEXT_WINDOW_KEEP_MIN", 12)
        cls.CONTEXT_WINDOW_TRIGGER_SUMMARY = cls._get_int("CONTEXT_WINDOW_TRIGGER_SUMMARY", 24)
        cls.RECENT_SUMMARIES_MAX = cls._get_int("RECENT_SUMMARIES_MAX", 3)
        
        # Retrieval settings
        cls.RECALL_SUMMARY_PER_QUERY = cls._get_int("RECALL_SUMMARY_PER_QUERY", 3)
        cls.RECALL_CONV_PER_SUMMARY = cls._get_int("RECALL_CONV_PER_SUMMARY", 4)
        cls.RERANK_TOP_SUMMARIES = cls._get_int("RERANK_TOP_SUMMARIES", 3)
        cls.RERANK_TOP_CONVS = cls._get_int("RERANK_TOP_CONVS", 6)
        
        # OpenAI settings
        cls.OPENAI_API_KEY = cls._get_str("OPENAI_API_KEY", "")
        cls.OPENAI_API_BASE = cls._get_str("OPENAI_API_BASE", "https://api.openai.com/v1")
        cls.CHAT_MODEL = cls._get_str("CHAT_MODEL", "gpt-4o")
        cls.TOOL_MODEL = cls._get_str("TOOL_MODEL", "gpt-4o")
        cls.CHAT_REASONING_EFFORT = cls._get_str("CHAT_REASONING_EFFORT", "low")
        cls.TOOL_REASONING_EFFORT = cls._get_str("TOOL_REASONING_EFFORT", "medium")
        
        # Embedding settings (default to OpenAI settings if not specified)
        cls.EMBEDDING_API_KEY = cls._get_str("EMBEDDING_API_KEY", cls.OPENAI_API_KEY)
        cls.EMBEDDING_API_BASE = cls._get_str("EMBEDDING_API_BASE", cls.OPENAI_API_BASE)
        cls.EMBEDDING_MODEL = cls._get_str("EMBEDDING_MODEL", "text-embedding-3-small")
        cls.EMBEDDING_DIMENSION = cls._get_int("EMBEDDING_DIMENSION", 1536)
        
        # Command settings
        cls.NEW_SESSION_COMMAND = cls._get_str("NEW_SESSION_COMMAND", "/new")
        cls.RESET_SESSION_COMMAND = cls._get_str("RESET_SESSION_COMMAND", "/reset")
        
        # Reranker settings
        cls.RERANK_API_KEY = cls._get_str("RERANK_API_KEY", "")
        cls.RERANK_MODEL = cls._get_str("RERANK_MODEL", "")
        cls.RERANK_API_BASE = cls._get_str("RERANK_API_BASE", "")
        
        # Telegram settings
        cls.TELEGRAM_BOT_TOKEN = cls._get_str("TELEGRAM_BOT_TOKEN", "")
        cls.TELEGRAM_USER_ID = cls._get_int("TELEGRAM_USER_ID", 0)
        cls.TELEGRAM_USE_MARKDOWN = cls._get_bool("TELEGRAM_USE_MARKDOWN", True)
        
        # Skills settings
        cls.ENABLE_SKILLS = cls._get_bool("ENABLE_SKILLS", True)
        cls.SKILLS_DIR = cls._get_str("SKILLS_DIR", "skills/")
        
        # MCP settings
        cls.ENABLE_MCP = cls._get_bool("ENABLE_MCP", False)
        mcp_config_path_str = cls._get_str("MCP_CONFIG_PATH", "mcp_servers.json")
        cls.MCP_CONFIG_PATH = Path.cwd() / mcp_config_path_str if mcp_config_path_str else Path.cwd() / "mcp_servers.json"
        
        # Web search settings
        cls.ENABLE_WEB_SEARCH = cls._get_bool("ENABLE_WEB_SEARCH", False)
        cls.JINA_API_KEY = cls._get_str("JINA_API_KEY", "")

    @classmethod
    def _ensure_dirs_exist(cls) -> None:
        """Ensure required directories exist"""
        os.makedirs(cls.DATA_DIR, exist_ok=True)

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
    def _get_bool(key: str, default: bool = False) -> bool:
        """Get boolean value from environment"""
        value = os.getenv(key, "").lower()
        return value in ("true", "1", "yes")




def init_config(profile: str) -> None:
    """Initialize configuration (convenience function)"""
    Config.init(profile)
