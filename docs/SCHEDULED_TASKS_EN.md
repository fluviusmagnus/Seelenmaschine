# Scheduled Task Feature Usage Guide

[中文](SCHEDULED_TASKS.md)

## Overview

Seelenmaschine has a powerful built-in scheduled task feature that supports:
- ⏰ **Smart Task Triggering**: After triggering, LLM generates personalized responses instead of directly sending fixed messages
- 🔄 **Periodic Tasks**: Execute at fixed intervals
- 📝 **Task Management**: List, pause, resume, cancel
- 💬 **Automatic message sending via Telegram

## Core Design Philosophy

**Unlike traditional scheduled tasks**, Seelenmaschine's scheduled tasks do not directly send preset messages to users. Instead:

1. When a task triggers, the `message` field content is sent to the **AI (LLM)**
2. The AI generates personalized, contextual reminders based on the task content and current conversation context
3. The AI's response is sent to the user and saved to memory

**Example Workflow**:
```
Task setting: message="Remind user to drink water"
         
When triggered → AI receives: "[SYSTEM_SCHEDULED_TASK] Task: Remind user to drink water"
         
AI generates: "Good afternoon! You've been working for a while, remember to stand up and stretch,
           and drink some water to recharge 💧 Would you like me to help adjust your schedule?"
         
User receives: The above personalized response (saved to memory)
```

## Usage Through Conversation

The simplest way is to directly tell the AI your needs, and it will call the `scheduled_task` skill:

### Add One-Time Reminder

```
You: Remind me about the meeting tomorrow at 3 PM
AI: [Calls scheduled_task skill]
    ✓ Task created (ID: abc123...)
    Name: Meeting Reminder
    Type: One-time
    Trigger at: 2026-01-29 15:00:00
    Message: Remind user about the 3 PM meeting and ask if they need any preparation
```

### Add Periodic Task

```
You: Remind me to drink water every morning at 8 AM
AI: [Calls scheduled_task skill]
    ✓ Task created (ID: def456...)
    Name: Daily Water Reminder
    Type: Recurring
    Interval: 1d
    Message: Suggest user drink a glass of water to start the day hydrated
```

### View All Tasks

```
You: List all my scheduled tasks
AI: [Calls scheduled_task skill]
    Active tasks (2):
    
    • Meeting Reminder (ID: abc123...)
      Type: once
      Trigger at: 2026-01-29 15:00:00
      Message: Remind user about the 3 PM meeting...
    
    • Daily Water Reminder (ID: def456...)
      Type: interval
      Interval: 1d
      Next run: 2026-01-29 08:00:00
      Message: Suggest user drink a glass of water...
```

### Manage Tasks

```
You: Pause task def456
AI: [Calls scheduled_task skill]
    ✓ Task paused: Daily Water Reminder

You: Resume task def456
AI: [Calls scheduled_task skill]
    ✓ Task resumed: Daily Water Reminder

You: Cancel task abc123
AI: [Calls scheduled_task skill]
    ✓ Task cancelled: Meeting Reminder
```

## Time Expressions

### One-Time Task Support

- **Unix Timestamp**: `1738051200`
- **ISO DateTime**: `2026-01-29T15:00:00`
- **Relative Time**:
  - `in 2 hours` - 2 hours later
  - `in 30 minutes` - 30 minutes later
  - `in 3 days` - 3 days later
  - `tomorrow` - tomorrow
  - `next week` - next week

### Periodic Task Support

Simple interval expressions:
- `30s` - Every 30 seconds
- `5m` - Every 5 minutes
- `1h` - Every hour
- `1d` - Every day
- `1w` - Every week

## Task Field Explanation

### `name` vs `message`

- **`name`**: The name of the task, used only for listing and identifying tasks. Keep it short, e.g., "Morning Reminder", "Water Break"

- **`message`**: **The task content for the AI to see**, not directly sent to the user! The AI generates personalized reminders based on this content.
  - Should specifically describe what to remind and suggest what action
  - Examples:
    - ✅ "Remind user to call Mom about weekend plans"
    - ✅ "Suggest user take a 5-minute break and stretch"
    - ✅ "Ask user about progress on the quarterly report"
    - ❌ "Remember to drink water" (too vague, AI cannot provide context)
    - ❌ "Check something" (too ambiguous)

## Preset Task Configuration

Configure tasks to auto-load at startup in `data/{profile}/scheduled_tasks.json`:

```json
[
  {
    "name": "Morning Check-in",
    "trigger_type": "interval",
    "trigger_config": {
      "interval": 86400
    },
    "message": "Ask user how they slept and what their focus is for today"
  },
  {
    "name": "Project Deadline Alert",
    "trigger_type": "once",
    "trigger_config": {
      "timestamp": 1738051200
    },
    "message": "Remind user that the quarterly report is due today and offer to help review it"
  }
]
```

Configuration file path is set in `.env`:
```ini
SCHEDULED_TASKS_CONFIG_PATH=scheduled_tasks.json
```

## Technical Details

### Message Format

When a task triggers, the message format sent to the LLM is as follows:

```json
{
  "role": "user",
  "content": "⚡ [Current Request]\n[SYSTEM_SCHEDULED_TASK]\nTask Name: Daily Water Reminder\nTrigger Time: 2026-01-29 08:00:00\nTask: Suggest user drink a glass of water to start the day hydrated\n\nPlease respond proactively based on this scheduled task."
}
```

### Data Storage Strategy

| Data | Saved to Database | Counted in Context | Description |
|------|-------------------|-------------------|-------------|
| Task message (`message`) | ❌ No | ❌ No | Only used to trigger LLM, not saved |
| Task name (`name`) | ✅ Yes | ❌ No | Used for listing and managing tasks |
| LLM generated response | ✅ Yes | ✅ Yes | Saved as normal conversation |

### Database Table Structure

```sql
CREATE TABLE scheduled_tasks (
    task_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    trigger_type TEXT NOT NULL CHECK(trigger_type IN ('once', 'interval')),
    trigger_config TEXT NOT NULL,  -- JSON
    message TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    next_run_at INTEGER NOT NULL,
    last_run_at INTEGER,
    status TEXT CHECK(status IN ('active', 'paused', 'completed')) DEFAULT 'active'
);
```

### Task Status

- `active`: Active status, will be executed by the scheduler
- `paused`: Paused status, will not be executed
- `completed`: Completed (one-time task after execution, or cancelled)

### Execution Mechanism

1. The scheduler checks for due tasks every 10 seconds
2. When a task triggers, construct the `[SYSTEM_SCHEDULED_TASK]` message and send it to the LLM
3. LLM generates a personalized response (can use memory search and other tools, **but cannot use scheduled_task tool**)
4. Response is sent to the user and saved to the database (counts in conversation history)
5. Update task status:
   - One-time task: set `status='completed'`
   - Periodic task: update `next_run_at` to the next execution time

### Timezone Handling

All timestamps are stored in UTC and converted to the configured timezone (`TIMEZONE`) for display.

## Programmatic Usage

If you need to use the scheduler directly in code:

```python
from core.database import DatabaseManager
from core.scheduler import TaskScheduler

# Initialize
db = DatabaseManager()
scheduler = TaskScheduler(db)

# Set message callback (Telegram bot will set automatically)
# Note: Callback now receives two parameters: message and task_name
def my_callback(message: str, task_name: str):
    print(f"Task '{task_name}' triggered with message: {message}")

scheduler.set_message_callback(my_callback)

# Start scheduler
scheduler.start()

# Add one-time task
task_id = scheduler.add_task(
    name="Test Reminder",
    trigger_type="once",
    trigger_config={"timestamp": 1738051200},
    message="Suggest user take a break and review today's progress"
)

# Add periodic task
task_id = scheduler.add_task(
    name="Hourly Check",
    trigger_type="interval",
    trigger_config={"interval": 3600},  # Every hour
    message="Ask user if they need anything or want to chat"
)

# Stop scheduler (on program exit)
scheduler.stop()
```

## Testing

Run unit tests:

```bash
.venv/bin/python -m pytest tests/test_scheduler.py -v
```

Test coverage:
- Task creation and querying
- One-time and periodic task execution
- Task status management
- JSON configuration loading
- Message callback mechanism (including task_name passing)

## Limitations and Notes

1. **Single-user mode**: Currently only supports single user (`TELEGRAM_USER_ID`)
2. **Precision**: Scheduler checks every 10 seconds, accuracy is ±10 seconds
3. **Persistence**: Tasks are stored in the database and automatically restored after restart
4. **Timezone**: Ensure `TIMEZONE` in `.env` is set correctly
5. **Tool restriction**: When processing scheduled tasks, LLM **cannot** use `scheduled_task` tool to create new tasks (to avoid loops)
6. **Token consumption**: Scheduled task triggers LLM calls will increase API costs

## Future Enhancements

- [ ] Support cron expressions
- [ ] Support task priorities
- [ ] Support task dependencies
- [ ] Support task execution history queries
- [ ] Support task failure retry mechanism
