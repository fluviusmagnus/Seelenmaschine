from typing import Dict, Any
from datetime import datetime, timedelta

from core.database import DatabaseManager
from utils.time import timestamp_to_str
from core.config import Config
from prompts import load_seele_json
from utils.logger import get_logger

logger = get_logger()

class MemorySearchTool:
    """Tool for LLM to query its own memory using keyword search"""

    def __init__(
        self,
        session_id: str,
        db: DatabaseManager,
        embedding_client=None,
        reranker_client=None,
    ):
        self.session_id = int(session_id)
        self.db = db
        self._disabled = False

    @property
    def name(self) -> str:
        return "search_memories"

    @property
    def description(self) -> str:
        return """Search your long-term memory (conversation history and summaries) using keywords and filters.

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

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": """Search keywords using FTS5 syntax.

Examples:
- "coffee" - find conversations about coffee
- "coffee morning" - bare multiple keywords usually behave like AND in FTS5; prefer "coffee AND morning" for clarity
- "coffee AND morning" - both keywords must appear
- "tea OR coffee" - either keyword is acceptable
- '"morning routine"' - exact phrase match
- "coffee NOT decaf" - include coffee but exclude decaf
- "(tea OR coffee) AND morning" - grouping with OR and AND

Leave empty to search using only filters (session_id, role, time range).
If you only want to inspect one session, leaving query empty is valid; prefer search_target='summaries' for a concise overview.""",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 10). Increase for broader searches, decrease for specific queries.",
                    "default": 10,
                },
                "role": {
                    "type": "string",
                    "enum": ["user", "assistant"],
                    "description": "Filter by speaker role. Use 'user' to search only user's messages, 'assistant' to search only your own responses.",
                },
                "time_period": {
                    "type": "string",
                    "enum": ["last_day", "last_week", "last_month", "last_year"],
                    "description": "Quick time filter for recent conversations. Use this when user mentions vague timeframes like 'recently', 'lately', 'the other day'.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Filter conversations from this date onwards. Format: YYYY-MM-DD or YYYY-MM-DD HH:MM:SS. Use when user specifies a date like 'since January', 'after last month'.",
                },
                "end_date": {
                    "type": "string",
                    "description": "Filter conversations until this date. Format: YYYY-MM-DD or YYYY-MM-DD HH:MM:SS. Use when user specifies a date range or 'before March'.",
                },
                "include_current_session": {
                    "type": "boolean",
                    "description": "Whether to include the current conversation session in results. Defaults to false. Set to true only when you need to search the current ongoing session as well.",
                    "default": False,
                },
                "session_id": {
                    "type": "integer",
                    "description": "Search only within a specific session_id. When provided, this takes precedence over include_current_session behavior. This can be used without query; if you only want to inspect a session, prefer search_target='summaries' first.",
                },
                "search_target": {
                    "type": "string",
                    "enum": ["all", "summaries", "conversations"],
                    "description": "Choose which memory type to search. Defaults to 'all'. If using only session_id without query, prefer 'summaries' to review the session overview before using 'conversations' for verbatim details.",
                    "default": "all",
                },
            },
            "required": [],
        }

    def disable(self) -> None:
        self._disabled = True

    def enable(self) -> None:
        self._disabled = False

    def is_disabled(self) -> bool:
        return self._disabled

    @staticmethod
    def _fts_syntax_error_message(details: str) -> str:
        """Build a consistent user-facing FTS syntax error message."""
        return (
            f"FTS5 query syntax error: {details}\n\n"
            'Valid examples:\n- Anna AND 电影\n- 电影 OR 音乐\n- "exact phrase"\n'
            "- (电影 OR 音乐) AND Anna"
        )

    @staticmethod
    def _invalid_query_message(error_msg: str) -> str:
        """Build a consistent validation error message for bad queries."""
        return (
            f"Invalid query syntax: {error_msg}\n\n"
            'Valid examples:\n- Anna AND 电影\n- 电影 OR 音乐\n- "exact phrase"\n'
            "- (电影 OR 音乐) AND Anna"
        )

    def _validate_fts_query(self, query: str) -> tuple[bool, str]:
        """Validate FTS5 query syntax and provide helpful error messages.

        Returns:
            (is_valid, error_message)
        """
        if not query:
            return True, ""

        # Check for common errors
        errors = []

        # Check for unmatched quotes
        if query.count('"') % 2 != 0:
            errors.append("Unmatched quotes in query")

        # Check for unmatched parentheses
        if query.count("(") != query.count(")"):
            errors.append("Unmatched parentheses in query")

        # Check for invalid operators at start/end
        operators = ["AND", "OR", "NOT"]
        words = query.split()
        if words and words[0] in operators:
            errors.append(f"Query cannot start with operator '{words[0]}'")
        if words and words[-1] in operators:
            errors.append(f"Query cannot end with operator '{words[-1]}'")

        if errors:
            return False, "; ".join(errors)

        return True, ""

    @staticmethod
    def _parse_date_filter(date_str: str, *, end_of_day: bool = False) -> int:
        """Parse a date filter string into a timezone-aware timestamp."""
        tz = Config.TIMEZONE
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            if end_of_day:
                dt = dt.replace(hour=23, minute=59, second=59)

        dt = dt.replace(tzinfo=tz)
        return int(dt.timestamp())

    @staticmethod
    def _time_period_start_timestamp(time_period: str) -> int | None:
        """Translate a named recent time period into a start timestamp."""
        now = datetime.now(Config.TIMEZONE)
        periods = {
            "last_day": timedelta(days=1),
            "last_week": timedelta(weeks=1),
            "last_month": timedelta(days=30),
            "last_year": timedelta(days=365),
        }
        delta = periods.get(time_period)
        if delta is None:
            return None
        return int((now - delta).timestamp())

    def _search_with_fts_guard(self, search_func, **kwargs):
        """Run a DB search and convert FTS syntax failures into user-facing text."""
        try:
            return search_func(**kwargs)
        except Exception as error:
            error_text = str(error)
            if "fts5" in error_text.lower() or "syntax" in error_text.lower():
                return self._fts_syntax_error_message(error_text)
            raise

    @staticmethod
    def _append_search_criteria(
        result: list[str],
        *,
        query: str,
        role: str,
        time_period: str,
        start_date: str,
        end_date: str,
        session_id: int | None,
        search_target: str,
    ) -> None:
        """Append a one-line summary of active search filters."""
        criteria = []
        if query:
            criteria.append(f"keywords: '{query}'")
        if role:
            criteria.append(f"role: {role}")
        if session_id is not None:
            criteria.append(f"session_id: {session_id}")
        if search_target != "all":
            criteria.append(f"target: {search_target}")
        if time_period:
            criteria.append(f"time: {time_period}")
        elif start_date or end_date:
            if start_date and end_date:
                criteria.append(f"time: {start_date} to {end_date}")
            elif start_date:
                criteria.append(f"time: from {start_date}")
            else:
                criteria.append(f"time: until {end_date}")

        if criteria:
            result.append(f"Search criteria: {', '.join(criteria)}\n")

    @staticmethod
    def _append_summary_results(
        result: list[str], summary_results: list[tuple[Any, ...]]
    ) -> None:
        """Append formatted summary matches to the output buffer."""
        if not summary_results:
            return

        result.append("== Related Summaries ==")
        for _summary_id, session_id, summary, first_ts, last_ts, _rank in summary_results:
            start_time_str = timestamp_to_str(first_ts, tz=Config.TIMEZONE)
            end_time_str = timestamp_to_str(last_ts, tz=Config.TIMEZONE)
            result.append(
                f"[{start_time_str} ~ {end_time_str}][session_id={session_id}] {summary}"
            )

    @staticmethod
    def _append_conversation_results(
        result: list[str], conversation_results: list[tuple[Any, ...]]
    ) -> None:
        """Append formatted conversation matches to the output buffer."""
        if not conversation_results:
            return

        seele_data = load_seele_json()
        bot_name = seele_data.get("bot", {}).get("name", "AI Assistant") or "AI Assistant"
        user_name = seele_data.get("user", {}).get("name", "User") or "User"
        role_to_name = {
            "user": user_name,
            "assistant": bot_name,
        }

        if result and not result[-1].startswith("=="):
            result.append("")

        result.append("== Related Conversations ==")
        for _conv_id, session_id, timestamp, conv_role, text, _rank in conversation_results:
            time_str = timestamp_to_str(timestamp, tz=Config.TIMEZONE)
            role_display = role_to_name.get(conv_role, conv_role)
            result.append(
                f"[{time_str}][session_id={session_id}] {role_display}: {text}"
            )

    def _sanitize_query(self, query: str) -> str:
        """Sanitize query to prevent FTS5 syntax errors.

        Specifically targets unquoted dates in YYYY-MM-DD format which cause
        "no such column" errors in FTS5 boolean queries.
        """
        import re

        if not query:
            return query

        # Split by quotes to identify parts outside quotes
        parts = query.split('"')

        date_pattern = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

        new_parts = []
        for i, part in enumerate(parts):
            if i % 2 == 0:
                # Outside quotes: find unquoted dates and wrap them in quotes
                # We use a callback to wrap the date
                new_part = date_pattern.sub(r'"\1"', part)
                new_parts.append(new_part)
            else:
                # Inside quotes: leave as is
                new_parts.append(part)

        return '"'.join(new_parts)

    async def execute(
        self,
        query: str = "",
        limit: int = 10,
        role: str = None,
        time_period: str = None,
        start_date: str = None,
        end_date: str = None,
        include_current_session: bool = False,
        session_id: int = None,
        search_target: str = "all",
    ) -> str:
        """Execute keyword-based memory search with optional filters"""
        if self._disabled:
            return "Memory search is disabled during response generation to prevent recursion"

        try:
            # Sanitize query to fix FTS5 issues with dates
            if query:
                query = self._sanitize_query(query)

            # Validate query syntax
            if query:
                is_valid, error_msg = self._validate_fts_query(query)

                if not is_valid:
                    return self._invalid_query_message(error_msg)

            if search_target not in {"all", "summaries", "conversations"}:
                return (
                    "Invalid search_target. Use one of: all, summaries, conversations"
                )

            # Parse time filters
            start_timestamp = None
            end_timestamp = None

            # Handle time_period presets
            if time_period:
                start_timestamp = self._time_period_start_timestamp(time_period)

            # Handle explicit date ranges (override time_period if provided)
            if start_date:
                try:
                    start_timestamp = self._parse_date_filter(start_date)
                except ValueError:
                    return f"Invalid start_date format: {start_date}. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS"

            if end_date:
                try:
                    end_timestamp = self._parse_date_filter(
                        end_date, end_of_day=True
                    )
                except ValueError:
                    return f"Invalid end_date format: {end_date}. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS"

            # Validate that at least one search criterion is provided
            if (
                not query
                and not role
                and not start_timestamp
                and not end_timestamp
                and session_id is None
            ):
                return "Please provide at least one search criterion (query, session_id, role, or time filter)"

            effective_session_id = session_id
            exclude_session_id = None if include_current_session else self.session_id
            exclude_recent_from_session_id = None
            exclude_recent_limit = 0

            if effective_session_id is not None:
                exclude_session_id = None
                if effective_session_id == self.session_id:
                    exclude_recent_from_session_id = self.session_id
                    exclude_recent_limit = Config.CONTEXT_WINDOW_KEEP_MIN
            else:
                exclude_recent_from_session_id = self.session_id
                exclude_recent_limit = Config.CONTEXT_WINDOW_KEEP_MIN

            summary_results = []
            conversation_results = []

            if search_target in {"all", "summaries"}:
                summary_results = self._search_with_fts_guard(
                    self.db.search_summaries_by_keyword,
                    query=query if query else None,
                    limit=limit if search_target == "summaries" else limit // 2,
                    session_id=effective_session_id,
                    exclude_session_id=exclude_session_id,
                    start_timestamp=start_timestamp,
                    end_timestamp=end_timestamp,
                )
                if isinstance(summary_results, str):
                    return summary_results

            if search_target in {"all", "conversations"}:
                conversation_results = self._search_with_fts_guard(
                    self.db.search_conversations_by_keyword,
                    query=query if query else None,
                    limit=limit if search_target == "conversations" else limit // 2,
                    session_id=effective_session_id,
                    exclude_session_id=exclude_session_id,
                    exclude_recent_from_session_id=exclude_recent_from_session_id,
                    exclude_recent_limit=exclude_recent_limit,
                    role=role,
                    start_timestamp=start_timestamp,
                    end_timestamp=end_timestamp,
                )
                if isinstance(conversation_results, str):
                    return conversation_results

            result = []
            self._append_search_criteria(
                result,
                query=query,
                role=role,
                time_period=time_period,
                start_date=start_date,
                end_date=end_date,
                session_id=effective_session_id,
                search_target=search_target,
            )
            self._append_summary_results(result, summary_results)
            self._append_conversation_results(result, conversation_results)

            if not summary_results and not conversation_results:
                return "No relevant memories found matching the search criteria"

            return "\n".join(result)

        except Exception as e:
            logger.error(f"Memory search failed: {e}", exc_info=True)
            return f"Memory search failed: {str(e)}"

