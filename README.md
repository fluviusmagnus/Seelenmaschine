# Seele Chat

A Python-based chatbot with persistent memory and personality, powered by OpenAI's language models.

## Features

- Maintains conversation history and generates summaries
- Remembers personality traits and user preferences across sessions
- Recalls relevant past conversations based on context
- Terminal-based interface with simple commands

## Setup

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and set your OpenAI API key:
   ```
   OPENAI_API_KEY=your-api-key-here
   ```

## Usage

Start the chat:
```bash
python src/main.py
```

### Commands

- `/save` - Save current session and start a new one
- `/reset` - Reset current session without saving
- `/exit` - Save and exit
- `/help` - Show help message

## Project Structure

```
.
├── config/             # Personality configuration files
├── memory/            # LanceDB database files
├── src/
│   ├── config.py      # Configuration and settings
│   ├── database.py    # Database operations
│   ├── memory.py      # Memory management
│   ├── chat.py        # Core chat functionality
│   └── main.py        # Entry point
├── .env               # Environment variables
└── requirements.txt   # Python dependencies
```

## Memory Model

The chatbot maintains several types of memory:

1. **Personality Memory**
   - Self-perception and traits
   - User profile and preferences
   - Stored in JSON files in config directory
   - Updated after each session

2. **Conversation Summaries**
   - Summaries of past sessions stored in LanceDB
   - Vector embeddings for semantic search
   - Includes timestamps and full conversation history

3. **Current Context**
   - Active conversation in memory
   - Automatically summarized when exceeding context limit
   - Relevant past conversations recalled based on context

## Configuration

The chatbot can be configured through environment variables in `.env`:

- `OPENAI_API_KEY` - Your OpenAI API key
- `OPENAI_API_BASE` - API base URL (default: https://api.openai.com/v1)
- `CHAT_MODEL` - Model for chat (default: gpt-3.5-turbo)
- `EMBEDDING_MODEL` - Model for embeddings (default: text-embedding-ada-002)

Additional settings can be found in `src/config.py`:

- `MAX_CONV_NUM` - Maximum conversations in context
- `REFRESH_EVERY_CONV_NUM` - Number of conversations before refreshing summary
- `RECALL_SESSION_NUM` - Number of relevant sessions to recall
- `RECALL_CONV_NUM` - Number of conversations to recall per session
