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
- 📱 **Telegram Bot Interface**: Supports Markdown v2 format
- 🌐 **Web Search**: Jina Deepsearch API integration
- 🔌 **MCP (Model Context Protocol) Support**:
   - Dynamically connect external tools and data sources
   - Support multiple transport methods (stdio, HTTP, SSE)
- ⏰ **Scheduled Tasks**: Support for one-time and interval tasks
- 🛡️ **Built-in Local Tools**:
  - File operations (read, write, edit, append)
  - File search (Grep content search, Glob pattern matching)
  - Shell command execution (with dangerous command detection and human approval)
- 📤 **File Sending**: Support sending generated files directly via Telegram
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
DEBUG_LOG_LEVEL=INFO
DEBUG_SHOW_FULL_PROMPT=false
DEBUG_LOG_DATABASE_OPS=false
TIMEZONE=Asia/Shanghai

# Context Window Configuration
CONTEXT_WINDOW_KEEP_MIN=12
CONTEXT_WINDOW_TRIGGER_SUMMARY=24
RECENT_SUMMARIES_MAX=3

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

# Web Search Configuration
ENABLE_WEB_SEARCH=false
JINA_API_KEY=

# Workspace Configuration (Restricts local file operations)
WORKSPACE_DIR=          # Optional, workspace root directory, defaults to data/<profile>/workspace
MEDIA_DIR=              # Optional, media file storage directory, defaults to WORKSPACE_DIR/media

# Skills Configuration
ENABLE_SKILLS=true
SKILLS_DIR=skills/
```

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

- `/new` - Archive current session and start a new session
- `/reset` - Delete current session and create a new session

### Advanced Search Features

The system supports FTS5 full-text search. You can let the LLM call the `search_memories` tool through natural language:

Example queries:
```
Search for our previous conversations about Anna and movies
Find what I said last week
Look for conversations containing "machine learning" or "AI"
```

Supported search syntax:
- Boolean operators: `AND`, `OR`, `NOT`
- Exact phrases: `"exact phrase"`
- Time filters: `last_day`, `last_week`, `last_month`
- Role filters: `role='user'` or `role='assistant'`
- Date ranges: `start_date`, `end_date`

See [Search Examples Documentation](docs/SEARCH_EXAMPLES.md) for details.

### Tool Invocation

The system integrates the following tool capabilities:

1. **Built-in Local Tools**
   - File operations (read, write, edit, append)
   - File search (Grep content search/Glob pattern matching)
   - Shell command execution (with danger detection and human approval)
2. **MCP (Model Context Protocol)** - External tools and data sources
3. **Memory Search** - Self-query memory
4. **Web Search** - Web search (requires enabling)
5. **Scheduled Tasks** - Task management
6. **File Send** - Telegram file sending

Control the enabling status of each tool through configuration files. Dangerous commands require user approval before execution.

## Project Structure

```
Seelenmaschine/
├── src/                          # Source code directory
│   ├── main_telegram.py          # Telegram Bot entry point
│   ├── config.py                 # Configuration management
│   ├── core/                     # Core modules
│   │   ├── database.py           # Database management (sqlite-vec)
│   │   ├── memory.py             # Memory system
│   │   ├── context.py            # Context Window management
│   │   ├── retriever.py          # Memory retrieval
│   │   └── scheduler.py          # Task scheduler
│   ├── llm/                      # LLM modules
│   │   ├── client.py             # LLM client
│   │   ├── embedding.py          # Embedding client
│   │   └── reranker.py           # Rerank client
│   ├── tools/                    # Tool system
│   │   ├── mcp_client.py         # MCP client
│   │   ├── memory_search.py      # Self-query tool
│   │   ├── scheduled_task_tool.py # Scheduled task tool
│   │   ├── send_telegram_file_tool.py # Telegram file sending tool
│   │   ├── file_io.py            # File operation tools
│   │   ├── file_search.py        # File search tools
│   │   └── shell.py              # Shell command execution tool
│   ├── tg_bot/                   # Telegram Bot interface
│   │   ├── bot.py                # Bot main logic
│   │   └── handlers.py           # Message handlers
│   ├── prompts/                  # Prompts
│   │   ├── system.py             # System prompts
│   │   ├── summary.py            # Summary prompts
│   │   └── memory_update.py      # Memory update prompts
│   └── utils/                    # Utility functions
│       ├── time.py               # Time processing
│       └── logger.py             # Logging utilities

├── template/                     # Template directory
│   └── seele.json                # Long-term memory template
├── tests/                        # Unit tests
│   ├── conftest.py               # pytest configuration
│   ├── test_database.py
│   ├── test_memory.py
│   ├── test_retriever.py
│   └── test_llm.py
├── migration/                    # Data migration tools
│   ├── migrate.py                # Unified migration tool
│   └── README.md                 # Migration tool documentation
├── data/                         # Data storage directory
│   └── <profile>/                # Profile data directory
├── requirements.txt              # Python dependencies
├── requirements-dev.txt          # Development dependencies
├── docs/                         # Documentation directory
│   ├── SCHEDULED_TASKS.md        # Scheduled tasks documentation
│   └── SEARCH_EXAMPLES.md        # Search feature examples
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

## Debug Mode

In debug mode, the program will:
- Log complete prompts sent to LLM (`DEBUG_SHOW_FULL_PROMPT=true`)
- Log database read/write operations (`DEBUG_LOG_DATABASE_OPS=true`)
- Save logs to external files

## Running Tests

```bash
pytest tests/
pytest tests/ -v                    # Verbose output
pytest tests/ --cov=src            # Test coverage
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

## License

This project uses the GPL-3.0 license. See the [LICENSE](LICENSE) file for details.
