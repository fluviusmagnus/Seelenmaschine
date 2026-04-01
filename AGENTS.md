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
- The project is now **async-first** in `core / memory / llm / tools`
- Core business logic should keep only one main implementation, and that implementation should be async
- Sync APIs should exist only as thin compatibility wrappers around async implementations
- Do not maintain long-term parallel sync/async business logic bodies for the same workflow
- Use the shared async wrapper helpers in `src/utils/async_utils.py`
- Standard wrapper expectations:
  - use `ensure_not_in_async_context(...)` before entering sync wrappers
  - use `run_sync(...)` instead of handwritten `run_until_complete` logic
- Sync wrappers should have consistent event-loop and error behavior across modules
- Telegram bot handlers, scheduler callbacks, MCP access, shell/file tools, and several LLM paths are async
- Use async entry points inside async contexts; sync wrappers must clearly reject being called from an async context
- Do not introduce new module-local event-loop helper implementations when the shared helper can be used
- This async-first refactor does **not** imply converting the SQLite layer itself to async

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

## Architecture Ownership and Refactor Style

### Ownership Boundary
- `adapter` is the transport / I/O boundary and should only own platform-specific ingress, egress, formatting, and delivery behavior
- `core` owns system behavior, runtime wiring, approval flow, session flow, tool execution, and file-delivery policy
- Practical rule: if code would still matter after removing Telegram, it belongs in `core`
- If code depends on Telegram update/message/output semantics, it belongs in `adapter`

### Where New Code Should Go
- Move ownership to `core` before adding new adapter helpers
- Do not let adapter-side code accumulate stateful workflow logic that is not inherently Telegram-specific
- Keep Telegram controllers and adapter services thin: they should assemble boundary services and delegate to `core`
- Prefer adding new behavior to existing core owners before introducing a new layer

### Refactor Direction
- Prefer deleting thin pass-through wrappers when they do not protect a real boundary
- Prefer collapsing short-lived transitional seams after ownership has stabilized
- Reduce duplicated `create_*`, `get_*`, and `attach_*` scaffolding when it adds ceremony more than clarity
- Do not reintroduce adapter-side runtime/manager/host/bridge layers for core behavior
- Do not introduce new façade/host/helper layers unless they clearly own distinct state, lifecycle, or policy

### Runtime Shape
- Keep `CoreBot` as the direct core runtime entry surface
- Keep adapter controllers focused on boundary orchestration, not business ownership
- Keep tool/runtime ownership inside `core`, especially in `core.tools` and `core.bot`

### Refactor Style
- Prefer small, low-risk simplification steps over speculative rewrites
- Optimize for reducing redundant abstraction layers
- Keep registrations and state access direct when extra indirection adds no ownership clarity
- Avoid splitting modules only for cosmetic reasons; split only when ownership becomes clearer
- Prefer deleting obsolete compatibility layers instead of preserving them indefinitely
- For sync/async cleanup, first collapse duplicate logic into the async path, then leave sync as a thin wrapper before deciding whether removal is safe
- When compatibility is still needed, prefer deprecated shims over keeping two full implementations alive

### Tests During Refactors
- Update tests to target the real owner of behavior, not historical shells
- For architecture cleanup, prefer focused regression coverage before broad rewrites
- Keep the existing Telegram/Core regression set healthy when changing ownership boundaries
- Add regression coverage when collapsing duplicated sync/async flows so behavior does not diverge again
- For wrapper APIs, test both:
  - sync calls from normal synchronous contexts succeed
  - sync calls from async contexts fail with clear errors
- For fallback-heavy areas such as `src/memory/seele.py`, prefer adding focused regression tests before further compression

### File Structure
- `src/` - All Python source code
- `src/core/` - Application coordination (`approval.py`, `config.py`, `conversation.py`, `database.py`, `scheduler.py`, `tools.py`)
- `src/memory/` - Memory subsystem (`manager.py`, `context.py`, `vector_retriever.py`, `recall.py`, `sessions.py`, `summaries.py`, `seele.py`)
- `src/llm/` - LLM clients and orchestration helpers (`chat_client.py`, `memory_client.py`, `request_executor.py`, `tool_loop.py`, `embedding.py`, `reranker.py`)
- `src/prompts/` - Prompt builders and prompt-related helpers (`system_prompt.py`, `chat_prompt.py`, `memory_prompts.py`)
- `src/adapter/telegram/` - Telegram adapter implementation
- `src/tools/` - Tool implementations (`memory_search.py`, `mcp_client.py`, `scheduled_tasks.py`, `file_io.py`, `file_search.py`, `shell.py`, `send_file.py`, `tool_trace.py`)
- `src/utils/` - Utilities (`async_utils.py`, `logger.py`, `time.py`, `text.py`)
- `data/<profile>/` - Profile-specific data directory
- `tests/` - Test files
- `migration/` - Database migration scripts
- `<profile>.env` - Profile config file in the repository root

### Async-First Refactor Notes
- The current architectural direction is: **async-first + thin sync wrapper**
- New code should follow that direction by default
- Avoid adding new dual-track sync/async implementations in `memory`, `llm`, and `tools`
- Prefer shared helpers and common internal async flows for:
  - session handling
  - retrieval/rerank pipelines
  - long-term memory patch/fallback/retry flows
  - client close / tool-call wrapper behavior
- Audit sync APIs before expanding them; if a sync API has no meaningful external need, prefer reducing it to an internal compatibility interface or removing it when safe

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
