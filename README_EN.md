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
3. Configure the `.env` file as described below
3. Run
   - Windows: `start.bat` or `start-flask-webui.bat`
   - Linux:
     1. Grant permissions
       ```bash
       chmod +x start.sh start-flask-webui.sh
       ```
     2. Execute `start.sh` or `start-flask-webui.sh`
       ```bash
       ./start.sh
       ```
       or
       ```bash
       ./start-flask-webui.sh
       ```
4. (For WebUI) Access `http://localhost:7860` in your browser

## Manual Installation Instructions
1. Clone the project repository
2. Create a virtual environment (optional)
3. Install dependencies (requires Python 3.11+)
```bash
pip install -r requirements.txt
```

## Configuration Instructions
1. Copy the `.env.example` file and rename it to `.env`
2. Configure the following parameters in the `.env` file:
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
MAX_CONV_NUM=20  # Maximum conversation turns
REFRESH_EVERY_CONV_NUM=10  # Number of conversation turns for each summary
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
Enter CLI mode directly in the terminal:
```bash
python src/main.py
```
Or, launch the web application provided by WebUI:
```bash
python src/main.py --flask [--host HOST] [--port PORT]
```
Parameter description:
```
--flask: Launch the Flask Web interface
--host: Specify the host address (default: 127.0.0.1)
--port: Specify the port number (default: 7860)
```

### Available Commands in CLI Mode
- `/reset`, `/r` - Reset the current session
- `/save`, `/s` - Archive the current session, start a new session
- `/saveandexit`, `/sq` - Archive the current session, exit the program
- `/exit`, `/quit`, `/q` - Save the current state and exit the program
- `/help`, `/h` - Display this help information

## Project Structure
```
src/
├── main.py          # Main program entry, controls flow
├── chatbot.py       # Chat logic implementation
├── llm.py           # Large language model interface
├── memory.py        # Memory system implementation
├── config.py        # Configuration management
├── prompts.py       # Prompt templates
└── utils.py         # Utility functions
data/                # Data storage directory
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
