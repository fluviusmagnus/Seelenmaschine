# Seelenmaschine
![](static/logo-horizontal.png)
Seelenmaschine is an LLM chatbot project with memory and personality. It can engage in plain text conversations through a terminal or WebUI, with a persistent memory system that remembers conversation history with users and forms an understanding of them.

⚠️ High-intensity AI programming warning!

## Main Features
- 🤖 Supports multiple large language models (via OpenAI-compatible API)
- 🧠 Sophisticated memory system, including:
  - Personality memory (self-awareness and user image)
  - Conversation and conversation summaries (long-term memory)
  - Current conversation (short-term memory)
- 💾 Local data persistence
  - Uses lancedb for vector data storage
  - Uses SQLite for storing conversations and session information
- 🔍 Intelligent memory retrieval
  - Automatically retrieves relevant historical conversations
  - Intelligently determines embedding context for retrieval results
  - Dynamically generates conversation summaries
- 🛠️ Complete session management functionality
- 🖥 Provides a user-friendly WebUI
- 🛜 Automatically execute websearch if needed
- 🔌 **MCP (Model Context Protocol) Support**
  - Dynamically connect to external tools and data sources
  - Supports multiple transport methods (stdio, HTTP, SSE)
  - Tools are decoupled from the main application for easy extension
  - See [MCP Usage Guide](MCP_USAGE.md) for details

## Technical Architecture
- Language models: Any model compatible with OpenAI API
- Vector database: lancedb
- Relational database: SQLite
- Development language: Python
- WebUI: Flask
- Websearch: Jina Deepsearch

## Quick Start
1. Ensure Python is installed
2. Clone the project repository
   ```bash
   git clone https://github.com/fluviusmagnus/Seelenmaschine.git
   ```
3. Configure the `<profile>.env` file as described below (e.g., `dev.env` or `production.env`)
4. Run
   - Windows: `start.bat <profile>` or `start-flask-webui.bat <profile>`
     ```cmd
     start.bat dev
     ```
     or
     ```cmd
     start-flask-webui.bat dev
     ```
   - Linux:
     1. Grant permissions
       ```bash
       chmod +x start.sh start-flask-webui.sh
       ```
     2. Execute `start.sh <profile>` or `start-flask-webui.sh <profile>`
       ```bash
       ./start.sh dev
       ```
       or
       ```bash
       ./start-flask-webui.sh dev
       ```
5. (For WebUI) Access `http://localhost:7860` in your browser

## Manual Installation Instructions
1. Clone the project repository
2. Create a virtual environment (optional)
3. Install dependencies (requires Python 3.11+)
```bash
pip install -r requirements.txt
```

## Configuration Instructions

### Profile Configuration System

Seelenmaschine supports multi-environment configuration. Using the profile parameter, you can use different configurations and data directories.

1. Copy the `.env.example` file and rename it to `<profile>.env` (e.g., `dev.env`, `production.env`)
2. Each profile will use an independent data directory: `data/<profile>/`
3. Configure the following parameters in the `<profile>.env` file:
```ini
# Debug settings
DEBUG_MODE=false  # Debug mode toggle true/false
# Basic identity settings
AI_NAME=Seelenmachine
USER_NAME=User
# Timezone settings
# Timezone of the user. May be different from server time.
# More codes see https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
TIMEZONE=Asia/Shanghai
# OpenAI API settings
OPENAI_API_KEY=your_api_key
OPENAI_API_BASE=your_api_base
CHAT_MODEL=your_preferred_model  # For example: gpt-4o. With tool calling enabled.
TOOL_MODEL=your_tool_model  # For memory management. Recommend using a reasoning model, e.g.: deepdeek/deepseek-r1
CHAT_REASONING_EFFORT=low # See documentation of your API provider 
TOOL_REASONING_EFFORT=medium
EMBEDDING_MODEL=your_embedding_model  # For example: text-embedding-3-small
EMBEDDING_DIMENSION=1536
# Memory system settings
MAX_CONV_NUM=20  # Maximum conversation messages
REFRESH_EVERY_CONV_NUM=10  # Number of conversation messages for each summary
RECALL_SESSION_NUM=2  # Number of relevant sessions to retrieve
RECALL_CONV_NUM=4  # Number of conversations to retrieve from relevant sessions
# Tools settings
ENABLE_WEB_SEARCH=false
# Optional, while free API is available
JINA_API_KEY=

# MCP settings
# Enable MCP (Model Context Protocol) support
ENABLE_MCP=true
# MCP configuration file path
MCP_CONFIG_PATH=mcp_servers.json

```
3. (Optional) Create `persona_memory.txt` and `user_profile.txt` in the `data` folder, fill in personality memory and user image

For more configuration suggestions and usage tips, please refer to the project [Wiki](https://github.com/fluviusmagnus/Seelenmaschine/wiki/%E4%BD%BF%E7%94%A8%E6%8A%80%E5%B7%A7).

## Usage Instructions

### CLI Mode

Enter CLI mode directly in the terminal:
```bash
python src/main.py <profile>
```

Examples:
```bash
python src/main.py dev
python src/main.py production
```

Or use the startup scripts:
```bash
# Linux/macOS
./start.sh dev

# Windows
start.bat dev
```

### Web UI Mode

Launch the Flask Web interface:
```bash
python src/main.py <profile> --flask [--host HOST] [--port PORT]
```

Examples:
```bash
python src/main.py dev --flask
python src/main.py production --flask --host 0.0.0.0 --port 8080
```

Or use the convenient startup scripts:
```bash
# Linux/macOS
./start-flask-webui.sh dev
./start-flask-webui.sh dev --host 0.0.0.0 --port 8080

# Windows
start-flask-webui.bat dev
start-flask-webui.bat dev --host 0.0.0.0 --port 8080
```

Parameter description:
```
<profile>: Required parameter, specifies the configuration file to use (e.g., dev, production)
--flask: Launch the Flask Web interface
--host: Specify the host address (default: 127.0.0.1)
--port: Specify the port number (default: 7860)
```

### Available Commands in CLI Mode
- `/reset`, `/r` - Reset the current session
- `/save`, `/s` - Archive the current session, start a new session
- `/saveandexit`, `/sq` - Archive the current session, exit the program
- `/exit`, `/quit`, `/q` - Save the current state and exit the program
- `/tools`, `/t` - Toggle tool calling permission (temporary setting)
- `/help`, `/h` - Display this help information

### Tool Control

The system provides a two-level tool control mechanism:

**Configuration-level switches** (requires restart to take effect):
- `ENABLE_WEB_SEARCH`: Controls whether to load web search tools
- `ENABLE_MCP`: Controls whether to load MCP tools

**Runtime switch** (takes effect immediately, temporary setting):
- **CLI mode**: Use `/t` or `/tools` command to toggle tool calling permission
- **Web mode**: Toggle the "Tool Calling" switch in the sidebar settings panel

The runtime switch allows you to temporarily disable or enable tool calling during a conversation without modifying configuration files or restarting the application. This is useful for pure text conversations or testing different scenarios.

**Note**: The runtime switch only works when configuration-level tools are enabled. If no tools are enabled in the configuration, the runtime switch will have no effect.

## Project Structure
```
Seelenmaschine/
├── src/                          # Source code directory
│   ├── main.py                  # Main program entry
│   ├── chatbot.py               # Core chat logic
│   ├── llm.py                   # LLM interface
│   ├── memory.py                # Memory management
│   ├── config.py                # Configuration management
│   ├── prompts.py               # Prompt templates
│   ├── tools.py                 # Tool implementations
│   ├── mcp_client.py            # MCP client
│   ├── flask_webui.py           # Flask Web interface
│   ├── utils.py                 # Utility functions
│   ├── templates/               # HTML templates
│   │   ├── base.html
│   │   └── index.html
│   └── static/                  # Static resources
│       ├── css/
│       │   └── main.css
│       └── js/
│           └── main.js
├── data/                         # Data storage directory
│   ├── persona_memory.txt       # Self-awareness
│   ├── user_profile.txt         # User profile
│   ├── chat_sessions.db         # SQLite database
│   └── lancedb/                 # LanceDB vector database
├── database_maintenance.py       # Database maintenance script
├── maintenance.sh / .bat         # Maintenance script shortcuts
├── start.sh / .bat              # CLI startup scripts
├── start-flask-webui.sh / .bat  # Web interface startup scripts
├── requirements.txt              # Python dependencies
├── mcp_servers.json             # MCP server configuration
├── .env                         # Environment configuration
├── .env.example                 # Configuration example
├── README.md                    # Project documentation (Chinese)
├── README_EN.md                 # Project documentation (English)
├── MCP_USAGE.md                 # MCP usage guide
├── DATABASE_MAINTENANCE_README.md  # Database maintenance guide
└── LICENSE                      # License
```

## Memory System Description
### Personality Memory
- Contains self-awareness and user image
- Updated at the end of the session
- Permanently stored in configuration files

### Conversation Summaries
- Automatically summarizes and archives completed sessions
- Provides long-term memory through retrieval of historical conversations
- Second-order retrieval, further locating specific conversations through conversation summaries
- Stored in the database

### Current Conversation
- Records current session content in real-time
- Automatically summarizes earlier conversations when exceeding the maximum number of turns
- Supports session recovery functionality

## Debug Mode
In debug mode, the program will:
- Record all content submitted to the large model
- Record database read and write operations (incomplete)
- Save logs in external files

These logs are very helpful for development debugging and system optimization.
