# AGENTS.md - Seelenmaschine Development Guide

This file provides guidelines for AI agents working on the Seelenmaschine codebase.

## Build, Lint, and Test Commands

### Running Application
```bash
# Telegram Bot mode
python src/main_telegram.py <profile>
./start-telegram.sh <profile>      # Linux/macOS
start-telegram.bat <profile>       # Windows
```

### Linting and Formatting
```bash
# Run ruff for linting (available in .venv)
.venv/bin/ruff check src/*.py

# Auto-fix issues
.venv/bin/ruff check --fix src/*.py

# Check specific file
.venv/bin/ruff check src/chatbot.py
```

### Testing
No test framework is currently set up. When adding tests, use pytest.

## Code Style Guidelines

### Imports
- Order: standard library → third-party → local modules
- Use absolute imports for local modules (e.g., `from config import Config`)
- Group imports with blank lines between categories
```python
import os
import logging
from datetime import datetime

from openai import OpenAI
from flask import Flask

from config import Config
from memory import MemoryManager
```

### Type Hints
- Use type hints for all function parameters and return values
- Import from typing module for complex types
```python
from typing import List, Dict, Optional, Tuple

def process_input(text: str, limit: int = 10) -> List[Dict[str, str]]:
    pass
```

### Naming Conventions
- Classes: PascalCase (e.g., `ChatBot`, `MemoryManager`)
- Functions/variables: snake_case (e.g., `process_user_input`, `session_id`)
- Constants: UPPER_SNAKE_CASE (e.g., `MAX_CONV_NUM`, `AI_NAME`)
- Private methods: underscore prefix (e.g., `_get_db`, `_ensure_mcp_connected`)
- Type variables in generic types: T (e.g., `List[T]`)

### Error Handling
- Use try/except blocks with specific exception types
- Log errors with logging module
- Provide meaningful error messages
```python
try:
    response = client.call()
except ValueError as e:
    logging.error(f"Invalid value: {e}")
    raise
except Exception as e:
    logging.error(f"Unexpected error: {e}", exc_info=True)
```

### Logging
- Use loguru instead of standard logging
- Import get_logger from utils.logger
```python
from utils.logger import get_logger

logger = get_logger()
logger.debug(f"Processing session {session_id}")
logger.info("MCP client connected")
logger.error(f"Failed to retrieve data: {error}")
```

### Configuration
- All configuration must go through the Config class in config.py
- Use Config.* for accessing settings
- Config is initialized with `init_config(profile)` before importing dependent modules
```python
from config import Config

if Config.DEBUG_MODE:
    logging.debug("Debug mode enabled")
```

### Database Operations
- Use DatabaseManager for SQLite operations (with sqlite-vec)
- Always close connections after use or use context managers
- Parameterize all queries to prevent SQL injection

### Async/Sync
- Most code is synchronous
- Use asyncio only for MCP client operations
- Event loops are managed in LLMClient._get_event_loop()

### Docstrings
- Use docstrings for public methods and classes
- Keep them concise but descriptive
```python
def search_related_memories(self, query: str, current_session_id: str) -> Tuple[List[str], List[str]]:
    """Search for related conversation summaries and conversations based on query.
    
    Args:
        query: The search query text
        current_session_id: Current session ID to exclude from results
        
    Returns:
        Tuple of (summary_results, conversation_results)
    """
```

### String Formatting
- Use f-strings for string interpolation
- Use str.format() or % only when necessary for backward compatibility
```python
message = f"Processing {item_type} with ID {item_id}"
```

### Class Design
- Use composition over inheritance where possible
- Initialize dependencies in __init__
- Use @staticmethod for methods that don't need instance access
- Keep methods focused and single-purpose

### File Structure
- src/ - All Python source code
- data/<profile>/ - Profile-specific data directory
- static/ - Static assets for WebUI
- templates/ - HTML templates for WebUI
- Profile config files: <profile>.env in root directory

### Memory System Patterns
- Use MemoryManager for all memory operations
- Conversations are stored with text_id for vector mapping
- Sessions can be active or archived
- Use blockquote tags `<blockquote>...</blockquote>` for memory citations

### MCP Integration
- MCP tools are loaded dynamically via MCPClient
- MCP is optional (controlled by ENABLE_MCP config)
- Web search is a fallback tool (controlled by ENABLE_WEB_SEARCH)
- Tools are cached in LLMClient._tools_cache

### Web UI
- Flask + SocketIO for real-time communication
- Thread-based async mode
- Use socketio.emit() for sending messages to client
- Global ChatBot instance is thread-safe with bot_lock

### Environment Files
- Never commit .env files with real API keys
- Use .env.example as template
- Each profile has its own .env file
