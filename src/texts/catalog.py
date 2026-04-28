"""Centralized user-facing and persisted static text.

Prompt templates in ``src/prompts`` intentionally stay with their builders.
This module owns non-prompt copy that is shown to users, returned by tools, or
stored as synthetic system/event messages.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Mapping, Optional


class TelegramTexts:
    """Telegram-facing copy."""

    START = (
        "Welcome to Seelenmaschine! 🤖\n\n"
        "I'm your AI companion with long-term memory.\n\n"
        "Commands:\n"
        "/help - Show this help message\n"
        "/new - Start a new session (archives current)\n"
        "/reset - Reset current session\n"
        "/approve - Approve a pending dangerous action\n"
        "/stop - Stop the current tool loop\n\n"
        "Just send me a message to start chatting!"
    )
    HELP = (
        "Available commands:\n\n"
        "/start - Welcome message\n"
        "/help - Show this help\n"
        "/new - Archive current session and start new\n"
        "/reset - Delete current session and start fresh\n"
        "/approve - Approve a pending dangerous action\n"
        "/stop - Stop the current tool loop\n\n"
        "Features:\n"
        "• Long-term memory across sessions\n"
        "• Vector-based memory retrieval\n"
        "• Scheduled tasks and reminders\n"
        "• Tool integration (MCP, Skills)\n\n"
        "Just chat naturally - I'll remember our conversations!"
    )
    MENU_COMMANDS = [
        ("new", "Archive current session and start new"),
        ("reset", "Delete current session and start fresh"),
        ("approve", "Approve a pending dangerous action"),
        ("stop", "Stop the current tool loop"),
        ("help", "Show help and available commands"),
        ("start", "Welcome message"),
    ]

    UNAUTHORIZED_ACCESS = "Unauthorized access."
    NEW_SESSION_SUCCESS = (
        "✓ New session created! Previous conversations have been summarized and "
        "archived.\n\n"
        "I still remember our history and can recall it when relevant."
    )
    RESET_SESSION_SUCCESS = (
        "✓ Session reset! Current conversation has been deleted.\n\n"
        "Starting fresh, but I still have memories from previous sessions."
    )
    NO_PENDING_ACTION = "No pending action to approve."
    STOP_SIGNAL_SENT = (
        "🛑 Stop signal sent. The current tool loop will stop at the next safe "
        "checkpoint."
    )
    NO_RUNNING_TOOL_LOOP = "No running tool loop to stop."
    CURRENT_TOOL_LOOP_STOPPED = "🛑 Current tool loop stopped."
    UNSUPPORTED_FILE_TYPE = "Unsupported file type."

    USER_ERROR_TITLES = {
        "message": "Sorry, an error occurred while processing your message.",
        "file": "Sorry, an error occurred while processing your file.",
        "scheduled_task": (
            "Sorry, an error occurred while processing a scheduled task."
        ),
    }
    DEFAULT_USER_ERROR_TITLE = (
        "Sorry, an error occurred while processing your request."
    )

    @staticmethod
    def operation_error(operation: str, details: str) -> str:
        return f"{operation}.\n\nDetails: {details}"

    @classmethod
    def user_error_text(
        cls,
        *,
        scenario: str,
        details: str,
        subject_label: str | None = None,
        subject: str | None = None,
    ) -> str:
        title = cls.USER_ERROR_TITLES.get(scenario, cls.DEFAULT_USER_ERROR_TITLE)
        lines = [title, ""]
        normalized_subject = subject.strip() if isinstance(subject, str) else ""
        normalized_label = subject_label.strip() if isinstance(subject_label, str) else ""
        if normalized_subject and normalized_label:
            lines.append(f"{normalized_label}: {normalized_subject}")
        lines.append(f"Details: {details}")
        return "\n".join(lines)


class ApprovalTexts:
    """Human-in-the-loop approval copy."""

    DELIVERY_FAILED_ABORT_REASON = "Approval request delivery failed."
    TIMEOUT_NOTICE = "⏰ Approval timed out. Action aborted."
    TIMEOUT_ABORT_ERROR = "Error: Approval timed out. The action was not approved."
    USER_DECLINED_REASON = "User declined this action."
    STOP_ALL_FURTHER_REASON = (
        "Error: The user rejected this action and requested that all further "
        "steps stop."
    )

    @staticmethod
    def request_approval(tool_name: str, arguments: Mapping[str, Any], reason: str) -> str:
        args_str = html.escape(json.dumps(arguments, ensure_ascii=False)[:800])
        return (
            f"⚠️ <b>DANGEROUS ACTION DETECTED</b> ⚠️\n\n"
            f"<b>Tool:</b> <code>{html.escape(tool_name)}</code>\n"
            f"<b>Reason:</b> <code>{html.escape(reason)}</code>\n"
            f"<b>Arguments:</b>\n<pre>{args_str}</pre>\n\n"
            f"Reply <b>/approve</b> to execute.\n"
            f"Any other message will <b>ABORT</b> this action, and your message "
            f"will be returned to the model as feedback for the current tool loop."
        )

    @staticmethod
    def approved_action_finished(
        *,
        tool_name: str,
        result_preview: str,
        error_like: bool,
    ) -> str:
        prefix = (
            "⚠️ <b>Approved action finished with an error-like result</b>"
            if error_like
            else "✅ <b>Approved action finished</b>"
        )
        return (
            f"{prefix}\n\n"
            f"<b>Tool:</b> <code>{html.escape(tool_name)}</code>\n"
            f"<b>Result preview:</b> <pre>{html.escape(result_preview)}</pre>"
        )

    @staticmethod
    def approved_action_failed(*, tool_name: str, error_preview: str) -> str:
        return (
            "❌ <b>Approved action failed unexpectedly</b>\n\n"
            f"<b>Tool:</b> <code>{html.escape(tool_name)}</code>\n"
            f"<b>Error:</b> <pre>{html.escape(error_preview)}</pre>"
        )


class EventTexts:
    """Synthetic event messages that may be persisted in memory."""

    DEFAULT_SCHEDULED_TASK_NAME = "Scheduled Task"

    @staticmethod
    def scheduled_task_event(
        *,
        task_message: str,
        task_name: str,
        trigger_time: str,
        task_id: Optional[str] = None,
    ) -> str:
        return (
            f"[Scheduled Task]\n"
            f"This is a trigger message. Now execute the task described below and "
            f"then continue the current conversation.\n\n"
            f"task_id: {task_id or 'unknown'}\n"
            f"name: {task_name}\n"
            f"trigger_time: {trigger_time}\n"
            f"message: {task_message}"
        )

    @staticmethod
    def received_file_event(
        *,
        file_type: str,
        original_name: str,
        saved_path: str,
        mime_type: Optional[str] = None,
        file_size: Optional[int] = None,
        caption: Optional[str] = None,
    ) -> str:
        message_lines = [
            "[File Event]\nThe user has sent a file.\n",
            f"File type: {file_type}",
            f"Original filename: {original_name}",
            f"Saved to: {saved_path}",
        ]
        if mime_type:
            message_lines.append(f"MIME type: {mime_type}")
        if file_size is not None:
            message_lines.append(f"File size: {file_size} bytes")
        if caption:
            message_lines.append(f"Caption: {caption}")
        return "\n".join(message_lines)

    @staticmethod
    def sent_file_event(
        *,
        sent_path: Path,
        delivery_method: str,
        saved_path: str,
        platform_label: str,
        mime_type: Optional[str] = None,
        caption: Optional[str] = None,
    ) -> str:
        message_lines = [
            f"[System Event] Assistant has sent a file via {platform_label}.",
            f"Delivery method: {delivery_method}",
            f"Filename: {sent_path.name}",
            f"Path: {saved_path}",
        ]
        if mime_type:
            message_lines.append(f"MIME type: {mime_type}")
        if caption:
            message_lines.append(f"Caption: {caption}")
        return "\n".join(message_lines)

    @staticmethod
    def saved_artifact_message(artifact: Mapping[str, Any]) -> str:
        lines = ["[Tool Returned File]"]
        for key in (
            "path",
            "filename",
            "mime_type",
            "size_bytes",
            "source",
            "content_kind",
        ):
            value = artifact.get(key)
            if value not in (None, ""):
                lines.append(f"{key}: {value}")
        return "\n".join(lines)


class ToolTexts:
    """Tool descriptions, schemas, and execution-result copy."""

    @staticmethod
    def error(message: str) -> str:
        return f"Error: {message}"

    @staticmethod
    def unknown_action(action: Any) -> str:
        return f"Unknown action: {action}"

    class ScheduledTask:
        DESCRIPTION = """Manage scheduled tasks like reminders and recurring messages.

WHEN TO USE:
- User asks to set a reminder, alarm, or notification for future time
- User wants recurring messages (daily, weekly, etc.)
- User needs to be reminded about something later
- User asks to cancel, pause, or check existing reminders/tasks
- User mentions "remind me", "set a timer", "every day at..."

AVAILABLE ACTIONS:
- add: Create a new task (one-time or recurring)
- list: Show all active tasks
- get: View details of a specific task
- cancel: Delete a task permanently
- pause: Temporarily stop a task (can be resumed)
- resume: Reactivate a paused task

TIME FORMATS:
- One-time tasks: "30m" (30 minutes), "2h" (2 hours), "1d" (1 day), "1w" (1 week), or specific datetime
- Recurring tasks: Use interval format like "1h" (every hour), "1d" (daily), "7d" (weekly)"""
        PARAMETER_DESCRIPTIONS = {
            "action": "Action to perform on tasks. Use 'add' to create new task, 'list' to see all tasks, 'get' for details, 'cancel' to delete, 'pause' to temporarily stop, 'resume' to reactivate.",
            "task_id": "Unique task identifier. Required for 'get', 'cancel', 'pause', and 'resume' actions. Get the ID from the 'list' action.",
            "name": "Task name for identification and listing purposes. A simple label like 'Morning reminder' or 'Water break' (required for 'add' action)",
            "trigger_type": "Task trigger type. 'once' = single reminder (e.g., 'in 30 minutes'), 'interval' = recurring (e.g., 'every day at 9am'). Required for 'add' action.",
            "time": "Primary time field for 'add'. Required for 'add' action.\n\nFor 'once' tasks:\n- The execution time\n- Supports duration like '30s', '5m', '2h', '1d', '1w'\n- Supports specific datetime like '2026-02-01 14:30:00'\n\nFor 'interval' tasks:\n- The repeat interval only, such as '30s', '5m', '1h', '1d', '7d'\n- Use 'start_time' if the recurring task should begin at a specific datetime\n\nExamples: '30m' (in 30 min for once), '1d' (every 1 day for interval)",
            "start_time": "Optional first execution time for recurring 'interval' tasks. Use this when the task should start at a specific datetime and then repeat according to 'time'. Example: start_time='2026-02-01 08:00:00' with time='1d' means first run at 8 AM, then every day.",
            "end_time": "Optional stop time for recurring 'interval' tasks. The task will keep running at the configured interval until this time is reached. A run exactly at end_time is still allowed, but no future run after end_time will be scheduled.",
            "timezone": "Optional IANA timezone name used to interpret time fields, such as 'Asia/Shanghai' or 'Europe/Berlin'. If omitted, the system default timezone is used.",
            "message": "The task content that will be sent to the AI (not directly to the user) when the task triggers. This message helps the AI understand what the task is about so it can generate an appropriate, contextual reminder for the user. Write something the AI can work with to create a helpful, conversational reminder. Examples: 'Remind user to call Mom about weekend plans', 'Suggest user take a break and drink water', 'Ask user about progress on the quarterly report'. This is NOT the final message the user sees - the AI will craft that based on this content. Required for 'add' action.",
        }
        UNNAMED_TASK = "Unnamed Task"
        NO_ACTIVE_TASKS = "No active tasks found."

        @staticmethod
        def task_created_once(
            *,
            task_id: str,
            name: str,
            trigger_at: str,
            message: str,
            timezone_name: Optional[str] = None,
        ) -> str:
            response = (
                f"✓ Task created (Task ID: {task_id})\n"
                f"Name: {name}\n"
                f"Type: One-time\n"
                f"Trigger at: {trigger_at}"
            )
            if timezone_name:
                response += f"\nTimezone: {timezone_name.strip()}"
            return response + f"\nMessage: {message}"

        @staticmethod
        def task_created_interval(
            *,
            task_id: str,
            name: str,
            interval: str,
            message: str,
            first_run: Optional[str] = None,
            end_time: Optional[str] = None,
            timezone_name: Optional[str] = None,
        ) -> str:
            response = (
                f"✓ Task created (Task ID: {task_id})\n"
                f"Name: {name}\n"
                f"Type: Recurring\n"
                f"Interval: {interval}"
            )
            if first_run:
                response += f"\nFirst run: {first_run}"
            if end_time:
                response += f"\nEnd time: {end_time}"
            if timezone_name:
                response += f"\nTimezone: {timezone_name.strip()}"
            return response + f"\nMessage: {message}"

        @staticmethod
        def task_not_found(task_id: str) -> str:
            return f"Task not found: {task_id}"

        @staticmethod
        def task_status_mismatch(expected_state: str, current_status: str) -> str:
            return f"Task is not {expected_state} (current status: {current_status})"

        @staticmethod
        def task_action_success(action: str, name: str) -> str:
            return f"✓ Task {action}: {name}"

    class FileIO:
        READ_DESCRIPTION = (
            "Read a file. Relative paths resolve from WORKSPACE_DIR.\n\n"
            "Use start_line/end_line to read a specific line range (output includes "
            "line numbers). Omit both to read the full file.\n"
        )
        WRITE_DESCRIPTION = (
            "Create or overwrite a file. Relative paths resolve from WORKSPACE_DIR."
        )
        REPLACE_DESCRIPTION = (
            "Replace a specific contiguous block of text in a file with new content. "
            "Use this for editing existing files. Requires exact match of the target "
            "text (including indentation and spaces). DO NOT include line numbers in "
            "target_text or replacement_text."
        )
        APPEND_DESCRIPTION = (
            "Append content to the end of a file. Relative paths resolve from "
            "WORKSPACE_DIR. Safely handles newlines and cross-platform writing."
        )
        PARAMETER_DESCRIPTIONS = {
            "file_path": "Path to the file.",
            "start_line": "First line to read (1-based, inclusive).",
            "end_line": "Last line to read (1-based, inclusive).",
            "content": "Content to write to the file.",
            "target_text": "The exact string to be replaced. Must be an exact character-sequence match including whitespace/indentation.",
            "replacement_text": "The new content to insert in place of the target text.",
            "allow_multiple": "If true, replace all occurrences. If false, fails if target_text appears more than once. Default is false.",
        }

        @staticmethod
        def path_does_not_exist(path: str) -> str:
            return f"Error: The file {path} does not exist."

        @staticmethod
        def path_is_not_file(path: str) -> str:
            return f"Error: The path {path} is not a file."

        @staticmethod
        def file_too_large(max_size: int) -> str:
            return f"Error: File is too large. Max size is {max_size} bytes."

    class FileSearch:
        GREP_DESCRIPTION = (
            "Search file contents by pattern, recursively. Relative paths resolve "
            "from WORKSPACE_DIR."
        )
        GLOB_DESCRIPTION = (
            'Find files matching a glob pattern (e.g. "*.py", "**/*.json"). '
            "Relative paths resolve from WORKSPACE_DIR."
        )
        PARAMETER_DESCRIPTIONS = {
            "pattern": "Search string (or regex when is_regex is True).",
            "glob_pattern": "Glob pattern to match.",
            "path": "File or directory to search in. Defaults to WORKSPACE_DIR.",
            "glob_path": "Root directory to search from. Defaults to WORKSPACE_DIR.",
            "is_regex": "Treat pattern as a regular expression. Defaults to False.",
            "case_sensitive": "Case-sensitive matching. Defaults to True.",
            "context_lines": "Context lines before and after each match. Defaults to 0.",
            "include_pattern": 'Only search files whose name matches this glob (e.g. "*.py").',
        }

    class SendFile:
        DESCRIPTION = """Send a local file to the current user.

WHEN TO USE:
- User asks you to send/export/deliver a generated file
- You created or found a file in the workspace and should proactively send it
- The result is best delivered as an attachment instead of pasted text

IMPORTANT:
- file_path must point to an existing local file in the workspace/media area
- Prefer file_type='auto' unless you are certain about the media type
- Use caption for a short delivery note shown with the file"""
        PARAMETER_DESCRIPTIONS = {
            "file_path": "Local path to the file to send. Relative paths are resolved from the workspace directory.",
            "caption": "Optional caption to attach to the file.",
            "file_type": "How the file should be sent. Use 'auto' to detect from MIME type and extension.",
        }
        FILE_TYPE_ERROR = (
            "Error: file_type must be one of auto, document, photo, video, audio, "
            "or voice"
        )

        @staticmethod
        def sent_result(
            *,
            delivery_method: Optional[str],
            resolved_path: Optional[str],
            caption: Optional[str],
        ) -> str:
            lines = ["✓ File sent to user"]
            if delivery_method:
                lines.append(f"Delivery method: {delivery_method}")
            if resolved_path:
                lines.append(f"Path: {resolved_path}")
            if caption:
                lines.append(f"Caption: {caption}")
            return "\n".join(lines)

    class MemorySearch:
        DESCRIPTION = """Search your long-term memory (conversation history and summaries) using keywords and filters.

WHEN TO USE:
- User asks about past conversations, previous topics, or things mentioned before
- You need to recall specific facts, preferences, or events from history
- The conversation references something from earlier sessions
- User asks "do you remember...", "what did we talk about...", "when did I say..."
- You need context from past interactions to provide accurate response

QUERY SYNTAX (FTS5):
- Single keyword: coffee
- Multiple bare keywords separated by spaces usually behave like AND in FTS5; prefer explicit AND/OR for clarity
- AND (both required): coffee AND morning
- OR (either acceptable): tea OR coffee
- Exact phrase: "morning routine"
- Exclude: coffee NOT decaf
- Grouping: (tea OR coffee) AND morning

MIXED-LANGUAGE QUERY NOTES:
- Queries containing CJK text may use a mixed-language n-gram fallback instead of raw FTS tokenization
- In that fallback path, boolean operators like AND/OR/NOT and parentheses are still supported
- Longer CJK phrases and explicit operators are usually more predictable than very short ambiguous terms

VECTOR-ASSISTED RECALL:
- For longer natural-language queries, this tool may supplement keyword matches with vector-retrieved summaries when keyword results are sparse
- Vector recall is used as a fallback supplement, not as a replacement for exact keyword / boolean filtering

BEST PRACTICES:
1. Use specific keywords relevant to the topic
2. Use the same language as the user's conversation (e.g., if user speaks Chinese, search with Chinese keywords)
3. Combine keywords with AND for precise results
4. Use time filters when timeframe is known
5. Use role filter to find specific speaker's messages
6. Start with broader keywords, then narrow down if needed
7. query is optional: you may search using only filters such as session_id, role, or time range
8. If you want to see what a specific session was about, prefer session_id + search_target="summaries" for a concise overview
9. Use session_id + search_target="conversations" only when you need verbatim messages from that session
10. By default, this tool excludes the current conversation session. Only set include_current_session=true when you explicitly need to search the current session as well.

COMMON PATTERNS:
- Browse one session overview: search_memories(session_id=60, search_target="summaries")
- Search inside one session: search_memories(query="预算", session_id=60, search_target="conversations")
- Filter-only search: search_memories(role="user", time_period="last_week")"""
        VALID_QUERY_EXAMPLES = (
            'Valid examples:\n- Anna AND 电影\n- 电影 OR 音乐\n- "exact phrase"\n'
            "- (电影 OR 音乐) AND Anna"
        )
        PARAMETER_DESCRIPTIONS = {
            "query": """Search keywords using FTS5 syntax.

Examples:
- "coffee" - find conversations about coffee
- "coffee morning" - bare multiple keywords usually behave like AND in FTS5; prefer "coffee AND morning" for clarity
- "coffee AND morning" - both keywords must appear
- "tea OR coffee" - either keyword is acceptable
- '"morning routine"' - exact phrase match
- "coffee NOT decaf" - include coffee but exclude decaf
- "(tea OR coffee) AND morning" - grouping with OR and AND

Leave empty to search using only filters (session_id, role, time range).
If you only want to inspect one session, leaving query empty is valid; prefer search_target='summaries' for a concise overview.
Queries containing CJK text may automatically use a mixed-language n-gram fallback that still supports AND/OR/NOT and parentheses.""",
            "limit": "Maximum number of results to return (default: 10). Increase for broader searches, decrease for specific queries.",
            "role": "Filter by speaker role. Use 'user' to search only user's messages, 'assistant' to search only your own responses.",
            "time_period": "Quick time filter for recent conversations. Use this when user mentions vague timeframes like 'recently', 'lately', 'the other day'.",
            "start_date": "Filter conversations from this date onwards. Format: YYYY-MM-DD or YYYY-MM-DD HH:MM:SS. Use when user specifies a date like 'since January', 'after last month'.",
            "end_date": "Filter conversations until this date. Format: YYYY-MM-DD or YYYY-MM-DD HH:MM:SS. Use when user specifies a date range or 'before March'.",
            "include_current_session": "Whether to include the current conversation session in results. Defaults to false. Set to true only when you need to search the current ongoing session as well.",
            "session_id": "Search only within a specific session_id. When provided, this takes precedence over include_current_session behavior. This can be used without query; if you only want to inspect a session, prefer search_target='summaries' first.",
            "search_target": "Choose which memory type to search. Defaults to 'all'. If using only session_id without query, prefer 'summaries' to review the session overview before using 'conversations' for verbatim details.",
        }

        @classmethod
        def fts_syntax_error(cls, details: str) -> str:
            return f"FTS5 query syntax error: {details}\n\n{cls.VALID_QUERY_EXAMPLES}"

        @classmethod
        def invalid_query(cls, error_msg: str) -> str:
            return f"Invalid query syntax: {error_msg}\n\n{cls.VALID_QUERY_EXAMPLES}"
