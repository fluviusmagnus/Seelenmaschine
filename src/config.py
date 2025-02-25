import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()


class Config:
    # 基础路径配置
    BASE_DIR = Path(__file__).parent.parent
    DATA_DIR = BASE_DIR / "data"
    LOGS_DIR = BASE_DIR

    # 数据库配置
    SQLITE_DB_PATH = DATA_DIR / "chat_sessions.db"
    LANCEDB_PATH = DATA_DIR / "lancedb"

    # 基本身份设定
    AI_NAME = os.getenv("AI_NAME", "Seelenmaschine")
    USER_NAME = os.getenv("USER_NAME", "User")

    # 记忆文件配置
    PERSONA_MEMORY_PATH = DATA_DIR / "persona_memory.txt"
    USER_PROFILE_PATH = DATA_DIR / "user_profile.txt"

    # 日志配置
    LOG_PATH = LOGS_DIR / "chatbot.log"
    DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"

    # OpenAI配置
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
    CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-3.5-turbo")
    TOOL_MODEL = os.getenv("TOOL_MODEL", "gpt-3.5-turbo")
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

    # 嵌入模型配置
    EMBEDDING_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "1536"))

    # 对话参数配置
    MAX_CONV_NUM = int(os.getenv("MAX_CONV_NUM", "20"))  # 保持上下文的最近对话轮数
    REFRESH_EVERY_CONV_NUM = int(
        os.getenv("REFRESH_EVERY_CONV_NUM", "10")
    )  # 每N轮对话触发总结
    RECALL_SESSION_NUM = int(
        os.getenv("RECALL_SESSION_NUM", "2")
    )  # 召回的相关session数量
    RECALL_CONV_NUM = int(
        os.getenv("RECALL_CONV_NUM", "4")
    )  # 从相关session召回的对话数量


# 确保目录存在
os.makedirs(Config.DATA_DIR, exist_ok=True)
os.makedirs(Config.LOGS_DIR, exist_ok=True)
