# Seelenmaschine

[中文](README.md)

![](static/logo-horizontal.png)

Seelenmaschine is an LLM chatbot project with memory and personality. It uses Telegram Bot for interaction and features a persistent three-layer memory system: short-term memory (current session), medium-term memory (vector-retrieved historical conversations), and long-term memory (structured personality and user profile).

⚠️ High-intensity AI programming warning!

## Key Features

- 🤖 **Support for Multiple Large Language Models** (via OpenAI-compatible API)
- 🧠 **Three-Layer Memory System**:
  - **Short-term Memory**: Context Window management, automatic summarization and session switching
  - **Medium-term Memory**: Intelligent retrieval based on Embedding + Rerank
  - **Long-term Memory**: JSON-structured personality and user profile
- 💾 **All-in-One Database**: SQLite + sqlite-vec, no additional vector database required
- 🔍 **Intelligent Memory Retrieval**:
  - Two-stage retrieval (Summary → Conversation)
  - Rerank model re-ranking
  - Time-aware context injection
  - FTS5 full-text search (supports boolean operators)
  - Self-query tool (LLM can actively search memories)
- 🛠️ **Complete Session Management**:
  - `/new` - Archive current session and create new session
  - `/reset` - Delete current session
  - `/stop` - Interrupt the currently active tool loop
- 📱 **Telegram Bot Interface**: Command menu, segmented replies, file upload/sending, and proactive scheduled messages
- 🔌 **MCP (Model Context Protocol) Support**:
   - Dynamically connect external tools and data sources
   - Support multiple transport methods (stdio, HTTP, SSE)
- ⏰ **Scheduled Tasks**: Support for one-time tasks, interval tasks, and timezone-aware scheduling
- 🧾 **Tool Trace Logging**: Records tool execution history and exposes `query_tool_history`
- 🛡️ **Built-in Local Tools**:
  - File operations (read, write, edit, append)
  - File search (Grep content search, Glob pattern matching)
  - Shell command execution (with dangerous command detection, human approval, and configurable timeout)
- 📤 **File Sending**: Support sending generated files directly to the current user
- 🗂️ **Tool / MCP Artifact Persistence**: Automatically save binary or base64 artifacts into `MEDIA_DIR/tool_artifacts/`
- 🤝 **Human-in-the-Loop**: Dangerous operations require user approval to prevent accidental modifications

## Technical Architecture

- **Language Model**: Any model supporting OpenAI-compatible API
- **Database**: SQLite + sqlite-vec (vector extension)
- **Web Framework**: python-telegram-bot
- **Async Framework**: asyncio
- **Testing**: pytest + pytest-asyncio
- **Logging**: loguru

## Quick Start

1. **Clone the repository**
   ```bash
   git clone https://github.com/fluviusmagnus/Seelenmaschine.git
   cd Seelenmaschine
   ```

2. **Install dependencies**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Linux/macOS
   # .venv\Scripts\activate  # Windows
   pip install -r requirements.txt
   ```

3. **Configure environment**
   ```bash
   cp .env.example hy.env  # Use your preferred profile name
   # Edit hy.env and fill in necessary configurations
   ```

4. **Run Telegram Bot**
   ```bash
   python src/main_telegram.py hy
   # Or use the quick script
   ./start-telegram.sh hy              # Linux/macOS
   start-telegram.bat hy               # Windows
   ```

## Configuration Guide

### Profile Configuration System

Seelenmaschine supports multi-environment configuration. You can use different configurations and data directories through the profile parameter.

1. Copy the `.env.example` file and rename it to `<profile>.env` (e.g., `hy.env`, `dev.env`)
2. Each profile will use an independent data directory: `data/<profile>/`
3. Configure the following parameters in the `<profile>.env` file:

```ini
# Basic Configuration
DEBUG_MODE=false
# Leave empty to auto-resolve from DEBUG_MODE:
# - DEBUG_MODE=true  => DEBUG
# - DEBUG_MODE=false => INFO
# Only set this explicitly when you want to override the default behavior.
DEBUG_LOG_LEVEL=
DEBUG_SHOW_FULL_PROMPT=false
DEBUG_LOG_DATABASE_OPS=false
TIMEZONE=Asia/Shanghai

# Workspace Path Configuration
# Leave empty to use data/<profile>/workspace and its media subdirectory.
WORKSPACE_DIR=
MEDIA_DIR=

# Context Window Configuration
CONTEXT_WINDOW_KEEP_MIN=12
CONTEXT_WINDOW_TRIGGER_SUMMARY=24
RECENT_SUMMARIES_MAX=3

# Tool Execution Configuration
TOOL_EXECUTION_TIMEOUT_SECONDS=90.0
TOOL_LOOP_MAX_ITERATIONS=30

# Memory Retrieval Configuration
RECALL_SUMMARY_PER_QUERY=3
RECALL_CONV_PER_SUMMARY=4
RERANK_TOP_SUMMARIES=3
RERANK_TOP_CONVS=6

# Chat API Configuration
OPENAI_API_KEY=your_api_key
OPENAI_API_BASE=https://api.openai.com/v1
CHAT_MODEL=gpt-4o
TOOL_MODEL=gpt-4o
CHAT_REASONING_EFFORT=low
TOOL_REASONING_EFFORT=medium

# Embedding Configuration
EMBEDDING_API_KEY=your_api_key
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_API_BASE=https://api.openai.com/v1
EMBEDDING_DIMENSION=1536

# Rerank Configuration (Optional)
RERANK_API_KEY=
RERANK_MODEL=
RERANK_API_BASE=

# Telegram Configuration
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_USER_ID=your_user_id

# MCP Configuration
ENABLE_MCP=false
MCP_CONFIG_PATH=mcp_servers.json
```

Note: the current config format **does not use inline `#` comments**. If you need comments, put them on separate lines so they are not parsed as part of the value.

Additional notes:

- `TOOL_EXECUTION_TIMEOUT_SECONDS` controls the default timeout for a single tool call
- `TOOL_LOOP_MAX_ITERATIONS` limits the maximum number of iterations in one tool loop
- `WORKSPACE_DIR` / `MEDIA_DIR` are **optional advanced settings**; leave them empty in `.env.example`-style configs to use the default paths
- `WORKSPACE_DIR` defaults to `data/<profile>/workspace`
- `MEDIA_DIR` defaults to `WORKSPACE_DIR/media`

### Data Directory Structure

```
data/<profile>/
├── seele.json           # Long-term memory (personality and user profile)
├── chatbot.db           # SQLite database
└── workspace/           # Accessible workspace directory (for local file operations)
    └── media/           # Media file storage directory
```

## Usage Guide

### Telegram Bot Mode

Start the Telegram Bot:
```bash
python src/main_telegram.py <profile>

# Or use the quick script (auto-detects virtual environment and dependencies)
./start-telegram.sh <profile>         # Linux/macOS
start-telegram.bat <profile>          # Windows
```

Examples:
```bash
# Run directly with Python
python src/main_telegram.py hy
python src/main_telegram.py dev

# Or use the quick script
./start-telegram.sh test
start-telegram.bat hy
```

### Available Commands

- `/start` - Show the welcome message
- `/help` - Show help information
- `/new` - Archive current session and start a new session
- `/reset` - Delete current session and create a new session
- `/approve` - Approve a pending dangerous action
- `/stop` - Stop the currently active tool loop

### Advanced Search Features

The system now supports an upgraded memory search pipeline. You can let the LLM call the `search_memories` tool through natural language:

Example queries:
```
Search for our previous conversations about Anna and movies
Find what I said last week
Look for conversations containing "machine learning" or "AI"
```

Currently implemented memory-search capabilities:
- **FTS5 full-text retrieval** for boolean / phrase / prefix queries
- **mixed-language n-gram fallback** for Chinese, Japanese, and mixed-script queries
- **vector-assisted recall** to supplement sparse natural-language summary / conversation results
- **weighted fusion** to rank summary and conversation candidates using both keyword and vector signals
- **optional rerank** to refine a small set of top summary / conversation candidates when a reranker is configured

Supported search syntax and filters:
- Boolean operators: `AND`, `OR`, `NOT`
- Exact phrases: `"exact phrase"`
- Time filters: `last_day`, `last_week`, `last_month`
- Role filters: `role='user'` or `role='assistant'`
- Date ranges: `start_date`, `end_date`

#### Summary / Conversation Ranking Rules (Weighted Scoring)

For results returned from `search_target="summaries"`, `search_target="conversations"`, or either branch of `search_target="all"`, ranking is performed in stages rather than by a single source:

1. **Coarse retrieval**
   - keyword retrieval first via FTS5 or the n-gram fallback
   - vector-retrieved summary / conversation candidates may be added when the query looks like natural language and keyword hits are sparse

2. **Weighted fusion**
   - each summary / conversation item is scored using multiple signals:
     - **keyword_origin**: whether the row came from an explicit keyword-hit path
     - **token_coverage**: how much of the query token set is covered in the retrieved text
     - **exact_match**: whether the whole query appears as a direct substring in the retrieved text
     - **lexical_overlap**: overlap based on mixed-language search units (CJK bigrams / non-CJK tokens)
     - **vector_similarity**: similarity converted from vector distance
     - **recency**: a light recency bonus
   - the current implementation uses approximate weights of:
     - `keyword_origin`: **0.22**
     - `token_coverage`: **0.18**
     - `exact_match`: **0.18**
     - `lexical_overlap`: **0.32**
     - `vector_similarity`: **0.28**
     - `recency`: **0.05**

3. **Optional rerank**
   - if a reranker is configured, the system reranks a small top candidate set after weighted fusion for summaries or conversations
   - rerank is **best-effort**: if no reranker is configured, or the call fails, the fused order is kept

In practice this means:
- strong keyword hits usually remain near the top
- stronger semantic matches can still outrank weaker keyword-only results
- Chinese / Japanese / mixed-language queries are more robust than with plain FTS5 alone

See [Search Examples Documentation](docs/SEARCH_EXAMPLES.md) for details.

### Tool Invocation

The system integrates the following tool capabilities:

1. **Built-in Local Tools**
   - File operations (read, write, edit, append)
   - File search (Grep content search/Glob pattern matching)
   - Shell command execution (with danger detection, human approval, and default timeout control)
2. **MCP (Model Context Protocol)** - External tools and data sources
3. **Memory Search** - Self-query memory
4. **Scheduled Tasks** - Task management
5. **File Send** - Send files to the current user
6. **Tool Trace Query** - Query recent tool execution history

Control the enabling status of each tool through configuration files. Dangerous commands require user approval before execution.

When a tool or MCP server returns binary content, file-like data, or a sufficiently long base64 text block, the system may automatically persist it into `MEDIA_DIR/tool_artifacts/` and return it back as a saved file artifact.

### Advanced Usage

#### Dynamically inject extra rules via workspace `AGENTS.md`

If you want to provide extra runtime constraints for a specific profile / workspace, you can place an `AGENTS.md` file at the workspace root. When building the system prompt, the project will automatically append an `<agents_md>...</agents_md>` block after `commands_and_agreements`, injecting that file content into the model context.

Behavior:

- **Inject when present**: if `WORKSPACE_DIR/AGENTS.md` exists and is readable, it will be added to the system prompt automatically
- **Ignore when absent**: no error is raised, and the normal conversation flow is unaffected
- **Takes effect on the next request immediately**: after editing or deleting `AGENTS.md`, no bot restart is required; the next prompt build / next request will read the latest content automatically
- **Scoped to the current workspace**: useful for setting different coding rules, project constraints, or tool-usage agreements for different profiles

Example:

```markdown
# AGENTS.md

## Workspace Rules
- Prefer small, low-risk changes
- Add tests before refactoring
- Avoid changing the `adapter` boundary unless necessary
```

If your profile uses the default workspace, the path is typically:

```text
data/<profile>/workspace/AGENTS.md
```

If you explicitly set `WORKSPACE_DIR` in `<profile>.env`, place `AGENTS.md` at the root of that directory instead.

#### Advanced MCP usage

This project provides **MCP integration capability** for connecting external tools and data sources, but it does **not provide native skills support**. In other words, the project itself does not implement the kind of built-in skills mechanism found in some AI coding tools.

However, **some MCP services may themselves provide skills-like capabilities, or even support subagent invocation**. Whether that is available depends on the specific MCP service you choose to connect, not on Seelenmaschine core itself.

Please note:

- **You need to find and choose a suitable implementation yourself**: connect MCP services that match your own needs
- **This project only provides MCP integration**: it does not bundle these extended capabilities
- **This project does not recommend any specific MCP service or solution**: please evaluate compatibility, stability, and security yourself

## Project Structure

```
Seelenmaschine/
├── src/                          # Source code directory
│   ├── main_telegram.py          # Telegram Bot entry point
│   ├── adapter/                  # Platform adapters
│   │   └── telegram/
│   │       ├── adapter.py        # Telegram app setup and lifecycle
│   │       ├── commands.py       # Telegram command handlers
│   │       ├── controller.py     # Telegram controller and service wiring
│   │       ├── delivery.py       # Segmented Telegram delivery
│   │       ├── files.py          # Telegram file ingress/egress
│   │       └── formatter.py      # Telegram response formatting
│   ├── core/                     # Core modules
│   │   ├── adapter_contracts.py  # Adapter callback contracts
│   │   ├── bot.py                # CoreBot runtime root
│   │   ├── config.py             # Configuration management
│   │   ├── conversation.py       # Conversation orchestration
│   │   ├── database.py           # Database management (sqlite-vec)
│   │   ├── file_service.py       # File artifact and delivery policy
│   │   ├── hitl.py               # Human-in-the-loop approval flow
│   │   ├── scheduler.py          # Task scheduler
│   │   └── tools.py              # Tool runtime/registry/execution orchestration
│   ├── llm/                      # LLM modules
│   │   ├── chat_client.py        # Chat client
│   │   ├── embedding.py          # Embedding client
│   │   ├── memory_client.py      # Memory-oriented model calls
│   │   ├── message_builder.py    # Chat message builder
│   │   ├── request_executor.py   # Request executor
│   │   ├── reranker.py           # Rerank client
│   │   └── tool_loop.py          # Tool-calling loop
│   ├── memory/                   # Memory subsystem
│   │   ├── context.py            # Context Window management
│   │   ├── manager.py            # Memory manager
│   │   ├── seele.py              # Long-term profile updates
│   │   ├── sessions.py           # Session handling
│   │   └── vector_retriever.py   # Vector retrieval
│   ├── prompts/                  # Prompts
│   │   ├── chat_prompt.py        # Chat message assembly
│   │   ├── memory_prompts.py     # Memory prompts
│   │   ├── runtime.py            # Prompt runtime assembly
│   │   └── system_prompt.py      # System prompt builder
│   ├── texts/                    # Text catalog
│   │   └── catalog.py            # Text catalog helpers
│   ├── tools/                    # Tool system
│   │   ├── file_io.py            # File operation tools
│   │   ├── file_search.py        # File search tools
│   │   ├── mcp_client.py         # MCP client
│   │   ├── memory_search.py      # Self-query tool
│   │   ├── scheduled_tasks.py    # Scheduled task tool
│   │   ├── send_file.py          # File sending tool
│   │   ├── shell.py              # Shell command execution tool
│   │   └── tool_trace.py         # Tool invocation tracing
│   └── utils/                    # Utility functions
│       ├── async_utils.py        # async/sync helpers
│       ├── logger.py             # Logging utilities
│       ├── text.py               # Text processing
│       ├── time.py               # Time processing
│       └── tool_safety.py        # Tool safety policy

├── docs/                         # Documentation directory
│   ├── README.md                 # Documentation index
│   ├── SCHEDULED_TASKS.md        # Scheduled tasks documentation
│   ├── SEARCH_EXAMPLES.md        # Search feature examples
│   └── REDUNDANCY_REFACTOR_PLAN.md # Current refactor progress ledger
├── template/                     # Template directory
│   └── seele.json                # Long-term memory template
├── tests/                        # Unit tests
├── migration/                    # Data migration tools
│   ├── migrate.py                # Unified migration tool
│   └── README.md                 # Migration tool documentation
├── data/                         # Data storage directory
│   └── <profile>/                # Profile data directory
├── static/                       # Static assets
├── requirements.txt              # Python dependencies
├── requirements-dev.txt          # Development dependencies
├── <profile>.env                 # Environment configuration
├── .env.example                  # Configuration example
├── start-telegram.sh             # Startup script (Linux/macOS)
├── start-telegram.bat            # Startup script (Windows)
├── migrate.sh                    # Migration tool quick script (Linux/macOS)
├── migrate.bat                   # Migration tool quick script (Windows)
├── AGENTS.md                     # AI-assisted development guide
├── README.md                     # Project description
└── LICENSE                       # License
```

## Memory System Explanation

### Short-term Memory (Context Window)

- Current session messages are kept in memory
- When messages reach `CONTEXT_WINDOW_TRIGGER_SUMMARY` (default 24), automatically summarize the earlier `CONTEXT_WINDOW_KEEP_MIN` (default 12) messages
- Manage sessions through `/new` and `/reset` commands

### Medium-term Memory (Vector Retrieval)

- All conversations and summaries are vectorized and stored
- Use Embedding model for preliminary retrieval
- Use Rerank model for precision ranking (optional)
- Retrieval results are injected into prompts with human-readable timestamps

### Long-term Memory (Personality Profile)

- Stored in structured JSON format in `seele.json`
- Synchronized and updated each time a new summary is generated
- Directly embedded into system prompts
- The current schema separates `emotions` and `needs`, each with `long_term` and `short_term` fields

## Debug and Runtime Notes

### Debug Mode

In debug mode, the program will:
- Log complete prompts sent to LLM (`DEBUG_SHOW_FULL_PROMPT=true`)
- Log database read/write operations (`DEBUG_LOG_DATABASE_OPS=true`)
- Log fuller response, tool-call, and tool-result debug details
- Save logs to external files

Log level rules:
- If `DEBUG_MODE=true` and `DEBUG_LOG_LEVEL` is empty, the effective level defaults to `DEBUG`
- If `DEBUG_MODE=false` and `DEBUG_LOG_LEVEL` is empty, the effective level defaults to `INFO`
- If `DEBUG_LOG_LEVEL` is explicitly set, that value takes precedence

Recommended usage: treat `DEBUG_MODE` as the main switch, and use `DEBUG_LOG_LEVEL` only when you need to override the default behavior.

### Local tool workspace

- Relative-path file operations resolve from `WORKSPACE_DIR`
- `WORKSPACE_DIR` defaults to `data/<profile>/workspace`
- `MEDIA_DIR` defaults to `WORKSPACE_DIR/media`
- File and shell tools are constrained to `WORKSPACE_DIR` / `MEDIA_DIR`; out-of-bounds actions require approval or are blocked
- Tool / MCP artifacts are saved under `MEDIA_DIR/tool_artifacts/` by default

## Running Tests

```bash
python -m pytest tests
python -m pytest -v tests           # Verbose output
python -m pytest tests --cov=src    # Test coverage
```

## Data Migration

After reconfiguring environment variables as required, use the unified migration tool to migrate data from old versions:

```bash
# Execute migration
python migration/migrate.py <profile>

# Or use the quick script (auto-detects virtual environment and dependencies)
./migrate.sh <profile>                # Linux/macOS
migrate.bat <profile>                 # Windows
```

The migration tool will:
1. Automatically detect required migration tasks (old database migration, text to JSON, FTS5 upgrade)
2. Automatically backup existing data
3. Execute migration and verify results

See [Migration Guide](migration/README.md) for details.

## Documentation Index

- [docs/README_EN.md](docs/README_EN.md) - Documentation overview
- [docs/SCHEDULED_TASKS_EN.md](docs/SCHEDULED_TASKS_EN.md) - Scheduled tasks guide
- [docs/SEARCH_EXAMPLES.md](docs/SEARCH_EXAMPLES.md) - Search examples
- [migration/README_EN.md](migration/README_EN.md) - Migration guide

## License

This project uses the GPL-3.0 license. See the [LICENSE](LICENSE) file for details.
