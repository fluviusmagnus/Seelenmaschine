import os
from dotenv import load_dotenv
from pathlib import Path
from zoneinfo import ZoneInfo


class Config:
    # 基础路径配置
    BASE_DIR = Path(__file__).parent.parent
    DATA_DIR = None  # 将在 init_config 中设置
    LOGS_DIR = BASE_DIR
    MCP_FILESYS = None  # 将在 init_config 中设置

    # 数据库配置
    SQLITE_DB_PATH = None  # 将在 init_config 中设置
    LANCEDB_PATH = None  # 将在 init_config 中设置

    # 基本身份设定
    AI_NAME = "Seelenmaschine"
    USER_NAME = "User"

    # 记忆文件配置
    PERSONA_MEMORY_PATH = None  # 将在 init_config 中设置
    USER_PROFILE_PATH = None  # 将在 init_config 中设置

    # 日志配置
    LOG_PATH = LOGS_DIR / "chatbot.log"
    DEBUG_MODE = False

    # OpenAI配置
    OPENAI_API_KEY = None
    OPENAI_API_BASE = "https://api.openai.com/v1"
    CHAT_MODEL = "gpt-4o"
    TOOL_MODEL = "gpt-4o"
    CHAT_REASONING_EFFORT = "low"
    TOOL_REASONING_EFFORT = "medium"
    EMBEDDING_MODEL = "text-embedding-3-small"

    # 嵌入模型配置
    EMBEDDING_DIMENSION = 1536

    # 对话参数配置
    MAX_CONV_NUM = 20  # 保持上下文的最近对话条数
    REFRESH_EVERY_CONV_NUM = 10  # 每N条对话触发总结
    RECALL_SESSION_NUM = 2  # 召回的相关session数量
    RECALL_CONV_NUM = 4  # 从相关session召回的对话数量

    # 时区设置
    TIMEZONE = ZoneInfo("Asia/Shanghai")

    # 工具配置
    ENABLE_WEB_SEARCH = False
    JINA_API_KEY = ""

    # MCP 配置
    ENABLE_MCP = False
    MCP_CONFIG_PATH = None  # 将在 init_config 中设置


def init_config(profile: str):
    """根据 profile 初始化配置"""
    # 1. 加载对应的 .env 文件
    env_file = Config.BASE_DIR / f"{profile}.env"
    if not env_file.exists():
        print(f"错误: 配置文件 {env_file} 不存在")
        exit(1)

    load_dotenv(env_file, override=True)

    # 2. 设置 DATA_DIR
    Config.DATA_DIR = Config.BASE_DIR / "data" / profile

    # 3. 重新计算所有依赖 DATA_DIR 的路径
    Config.MCP_FILESYS = Config.DATA_DIR / "filesystem"
    Config.SQLITE_DB_PATH = Config.DATA_DIR / "chat_sessions.db"
    Config.LANCEDB_PATH = Config.DATA_DIR / "lancedb"
    Config.PERSONA_MEMORY_PATH = Config.DATA_DIR / "persona_memory.txt"
    Config.USER_PROFILE_PATH = Config.DATA_DIR / "user_profile.txt"

    # 4. 重新加载环境变量配置
    Config.AI_NAME = os.getenv("AI_NAME", "Seelenmaschine")
    Config.USER_NAME = os.getenv("USER_NAME", "User")
    Config.DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"

    Config.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    Config.OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
    Config.CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-4o")
    Config.TOOL_MODEL = os.getenv("TOOL_MODEL", "gpt-4o")
    Config.CHAT_REASONING_EFFORT = os.getenv("CHAT_REASONING_EFFORT", "low")
    Config.TOOL_REASONING_EFFORT = os.getenv("TOOL_REASONING_EFFORT", "medium")
    Config.EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

    Config.EMBEDDING_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "1536"))

    Config.MAX_CONV_NUM = int(os.getenv("MAX_CONV_NUM", "20"))
    Config.REFRESH_EVERY_CONV_NUM = int(os.getenv("REFRESH_EVERY_CONV_NUM", "10"))
    Config.RECALL_SESSION_NUM = int(os.getenv("RECALL_SESSION_NUM", "2"))
    Config.RECALL_CONV_NUM = int(os.getenv("RECALL_CONV_NUM", "4"))

    Config.TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Asia/Shanghai"))

    Config.ENABLE_WEB_SEARCH = os.getenv("ENABLE_WEB_SEARCH", "false").lower() == "true"
    Config.JINA_API_KEY = os.getenv("JINA_API_KEY", "")

    Config.ENABLE_MCP = os.getenv("ENABLE_MCP", "false").lower() == "true"
    Config.MCP_CONFIG_PATH = Config.BASE_DIR / os.getenv(
        "MCP_CONFIG_PATH", "mcp_servers.json"
    )

    # 5. 确保目录存在
    os.makedirs(Config.DATA_DIR, exist_ok=True)
    os.makedirs(Config.LOGS_DIR, exist_ok=True)
