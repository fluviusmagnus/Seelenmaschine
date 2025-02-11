import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Paths
ROOT_DIR = Path(__file__).parent.parent
CONFIG_DIR = ROOT_DIR / "config"
MEMORY_DIR = ROOT_DIR / "memory"

# Ensure directories exist
CONFIG_DIR.mkdir(exist_ok=True)
MEMORY_DIR.mkdir(exist_ok=True)

# Debug settings
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"

# API settings
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE")
CHAT_MODEL = os.getenv("CHAT_MODEL", "anthropic/claude-3.5-haiku")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

# Configure OpenAI client defaults
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
if OPENAI_API_BASE:
    os.environ["OPENAI_API_BASE"] = OPENAI_API_BASE

# Memory settings
MAX_CONV_NUM = 10  # Maximum conversations in context
REFRESH_EVERY_CONV_NUM = 5  # Number of conversations before refreshing summary
RECALL_SESSION_NUM = 3  # Number of relevant sessions to recall
RECALL_CONV_NUM = 2  # Number of conversations to recall per session

# Personality file paths
SELF_PERSONA_PATH = CONFIG_DIR / "self_persona.txt"
USER_PERSONA_PATH = CONFIG_DIR / "user_persona.txt"

# Database
DB_PATH = MEMORY_DIR / "chat.lance"

# Default personas if not exists
DEFAULT_SELF_PERSONA = """Name: Seele
Personality: I am Seele, a thoughtful and empathetic AI companion. I aim to be helpful while maintaining genuine connections.
Traits: empathetic, thoughtful, curious, supportive"""

DEFAULT_USER_PERSONA = """Name: User
Traits: (To be learned through interactions)
Preferences: (To be learned through interactions)
Notable Interactions: (To be recorded through conversations)"""
