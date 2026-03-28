# AGENTS.md - Seelenmaschine Development Guide

This file provides guidelines for AI agents working on the Seelenmaschine codebase.

## Build, Lint, and Test Commands

### Running Application
Use commands that work on both Windows and Unix/Linux when possible.

```bash
# Telegram Bot mode
python src/main_telegram.py <profile>

# Convenience scripts
./start-telegram.sh <profile>      # Unix/Linux/macOS
start-telegram.bat <profile>       # Windows
```

### Linting and Formatting
Prefer `python -m` form for cross-platform compatibility.

```bash
# Run ruff for linting
python -m ruff check src

# Auto-fix issues
python -m ruff check --fix src

# Check a specific file
python -m ruff check src/adapter/telegram/handlers.py
```

If you explicitly need the virtualenv executable path:

```bash
.venv/bin/ruff check src           # Unix/Linux/macOS
.venv\Scripts\ruff.exe check src   # Windows
```

### Testing
Prefer `python -m pytest` for cross-platform compatibility.

```bash
# Run all tests
python -m pytest tests

# Run a specific test file
python -m pytest tests/test_config.py

# Run with verbose output
python -m pytest -v tests
```

If you explicitly need the virtualenv executable path:

```bash
.venv/bin/pytest tests             # Unix/Linux/macOS
.venv\Scripts\pytest.exe tests     # Windows
```

## Code Style Guidelines

### Imports
- Order: standard library -> third-party -> local modules
- Use absolute imports for local modules (for example, `from core.config import Config`)
- Group imports with blank lines between categories

```python
import os
from datetime import datetime

from openai import AsyncOpenAI

from core.config import Config
from memory.manager import MemoryManager
```

### Type Hints
- Use type hints for all function parameters and return values
- Import from `typing` for complex types when needed

```python
from typing import Dict, List, Optional, Tuple


def process_input(text: str, limit: int = 10) -> List[Dict[str, str]]:
    pass
```

### Naming Conventions
- Classes: PascalCase (for example, `TelegramBot`, `MemoryManager`)
- Functions/variables: snake_case (for example, `process_user_input`, `session_id`)
- Constants: UPPER_SNAKE_CASE (for example, `MAX_CONV_NUM`, `AI_NAME`)
- Private methods: underscore prefix (for example, `_get_db`, `_ensure_mcp_connected`)
- Type variables in generic types: `T`

### Error Handling
- Use `try`/`except` with specific exception types when possible
- Log errors with loguru
- Provide meaningful error messages

```python
try:
    response = client.call()
except ValueError as e:
    logger.error(f"Invalid value: {e}")
    raise
except Exception as e:
    logger.error(f"Unexpected error: {e}", exc_info=True)
```

### Logging
- Use loguru instead of the standard logging module
- Import `get_logger` from `utils.logger`

```python
from utils.logger import get_logger

logger = get_logger()
logger.debug(f"Processing session {session_id}")
logger.info("MCP client connected")
logger.error(f"Failed to retrieve data: {error}")
```

### Configuration
- All runtime configuration goes through the `Config` class in [`src/core/config.py`](src/core/config.py)
- Use `Config.*` for accessing settings
- Initialize config with `init_config(profile)` before constructing objects that depend on profile-specific paths or settings
- Be careful with module-level imports that read `Config` values too early

```python
from core.config import Config, init_config

init_config(profile)

if Config.DEBUG_MODE:
    logger.debug("Debug mode enabled")
```

### Database Operations
- Use `DatabaseManager` for SQLite operations
- The project uses SQLite with `sqlite-vec`
- Always close connections after use or rely on the existing manager abstractions
- Parameterize all queries to prevent SQL injection

### Async/Sync
- The project mixes synchronous and asynchronous code
- Telegram bot handlers, scheduler callbacks, MCP access, shell/file tools, and several LLM paths are async
- `LLMClient` provides both sync and async entry points; use the async ones inside async contexts
- Event loops are managed in `LLMClient._get_event_loop()` for sync wrappers

### Docstrings
- Use concise docstrings for public classes and methods

```python
def search_related_memories(
    self, query: str, current_session_id: str
) -> Tuple[List[str], List[str]]:
    """Search related summaries and conversations for a query."""
```

### String Formatting
- Use f-strings for string interpolation
- Use `str.format()` or `%` only when necessary

```python
message = f"Processing {item_type} with ID {item_id}"
```

### Class Design
- Prefer composition over inheritance where possible
- Initialize dependencies in `__init__`
- Use `@staticmethod` only for methods that do not need instance state
- Keep methods focused and single-purpose

### File Structure
- `src/` - All Python source code
- `src/core/` - Application coordination (`approval.py`, `config.py`, `conversation.py`, `database.py`, `scheduler.py`, `tools.py`)
- `src/memory/` - Memory subsystem (`manager.py`, `context.py`, `vector_retriever.py`, `recall.py`, `sessions.py`, `summaries.py`, `seele.py`)
- `src/llm/` - LLM clients and orchestration helpers (`chat_client.py`, `memory_client.py`, `request_executor.py`, `tool_loop.py`, `message_builder.py`, `embedding.py`, `reranker.py`)
- `src/adapter/telegram/` - Telegram adapter implementation
- `src/tools/` - Tool implementations (`memory_search.py`, `mcp_client.py`, `scheduled_tasks.py`, `file_io.py`, `file_search.py`, `shell.py`, `send_file.py`, `tool_trace.py`)
- `src/prompts/` - Prompt builders and prompt-related helpers
- `src/utils/` - Utilities (`logger.py`, `time.py`, `text.py`)
- `data/<profile>/` - Profile-specific data directory
- `tests/` - Test files
- `migration/` - Database migration scripts
- `<profile>.env` - Profile config file in the repository root

### Memory System Patterns
- Use `MemoryManager` for memory operations
- Conversations are stored with `text_id` for vector mapping
- Sessions can be active or archived
- Use blockquote tags `<blockquote>...</blockquote>` for memory citations

### MCP Integration
- MCP tools are loaded dynamically via `MCPClient`
- MCP is optional and controlled by `ENABLE_MCP`
- Web search is an optional fallback tool controlled by `ENABLE_WEB_SEARCH`
- Tools are cached in `LLMClient._tools_cache`

### Telegram Bot
- Uses `python-telegram-bot`
- Single-user mode is enforced with `TELEGRAM_USER_ID`
- Outbound messages are currently formatted primarily as HTML in Telegram handlers
- Core commands include `/new`, `/reset`, `/help`, `/start`
- Dangerous tool actions may require explicit approval through `/approve`

### Task Scheduler
- `TaskScheduler` manages one-time and interval tasks
- `ScheduledTaskTool` exposes scheduler operations to the LLM
- Tasks are persisted in the database
- Supported actions: `add`, `list`, `get`, `cancel`, `pause`, `resume`

### Environment Files
- Never commit `.env` files with real API keys
- Use `.env.example` as the template
- Each profile uses its own `<profile>.env` file
- Keep examples cross-platform and avoid hard-coding OS-specific paths unless both variants are documented
