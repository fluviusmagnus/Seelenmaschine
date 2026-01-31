from typing import Dict, Any

from core.database import DatabaseManager
from utils.time import timestamp_to_str
from config import Config
from utils.logger import get_logger

logger = get_logger()


DISABLE_SEARCH_MEMORIES = False


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
6. Start with broader keywords, then narrow down if needed"""

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
- "coffee AND morning" - both keywords must appear
- "tea OR coffee" - either keyword is acceptable
- '"morning routine"' - exact phrase match
- "coffee NOT decaf" - include coffee but exclude decaf
- "(tea OR coffee) AND morning" - grouping with OR and AND

Leave empty to search using only filters (role, time range).""",
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
            },
            "required": [],
        }

    def disable(self) -> None:
        global DISABLE_SEARCH_MEMORIES
        DISABLE_SEARCH_MEMORIES = True

    def enable(self) -> None:
        global DISABLE_SEARCH_MEMORIES
        DISABLE_SEARCH_MEMORIES = False

    def is_disabled(self) -> bool:
        global DISABLE_SEARCH_MEMORIES
        return DISABLE_SEARCH_MEMORIES

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
    ) -> str:
        """Execute keyword-based memory search with optional filters"""
        if DISABLE_SEARCH_MEMORIES:
            return "Memory search is disabled during response generation to prevent recursion"

        try:
            from datetime import datetime, timedelta

            # Sanitize query to fix FTS5 issues with dates
            if query:
                query = self._sanitize_query(query)

            # Validate query syntax
            if query:
                is_valid, error_msg = self._validate_fts_query(query)

                if not is_valid:
                    return f'Invalid query syntax: {error_msg}\n\nValid examples:\n- Anna AND 电影\n- 电影 OR 音乐\n- "exact phrase"\n- (电影 OR 音乐) AND Anna'

            # Parse time filters
            start_timestamp = None
            end_timestamp = None

            # Handle time_period presets
            if time_period:
                tz = Config.TIMEZONE  # Already a ZoneInfo object
                now = datetime.now(tz)

                if time_period == "last_day":
                    start_timestamp = int((now - timedelta(days=1)).timestamp())
                elif time_period == "last_week":
                    start_timestamp = int((now - timedelta(weeks=1)).timestamp())
                elif time_period == "last_month":
                    start_timestamp = int((now - timedelta(days=30)).timestamp())
                elif time_period == "last_year":
                    start_timestamp = int((now - timedelta(days=365)).timestamp())

            # Handle explicit date ranges (override time_period if provided)
            if start_date:
                try:
                    tz = Config.TIMEZONE  # Already a ZoneInfo object
                    # Try parsing with time first, then date only
                    try:
                        dt = datetime.strptime(start_date, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        dt = datetime.strptime(start_date, "%Y-%m-%d")
                    dt = tz.localize(dt)
                    start_timestamp = int(dt.timestamp())
                except ValueError:
                    return f"Invalid start_date format: {start_date}. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS"

            if end_date:
                try:
                    tz = Config.TIMEZONE  # Already a ZoneInfo object
                    try:
                        dt = datetime.strptime(end_date, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        dt = datetime.strptime(end_date, "%Y-%m-%d")
                        # Set to end of day
                        dt = dt.replace(hour=23, minute=59, second=59)
                    dt = tz.localize(dt)
                    end_timestamp = int(dt.timestamp())
                except ValueError:
                    return f"Invalid end_date format: {end_date}. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS"

            # Validate that at least one search criterion is provided
            if not query and not role and not start_timestamp and not end_timestamp:
                return "Please provide at least one search criterion (query, role, or time filter)"

            # Search summaries by keyword (exclude current session)
            try:
                summary_results = self.db.search_summaries_by_keyword(
                    query=query if query else None,
                    limit=limit // 2,
                    exclude_session_id=self.session_id,
                    start_timestamp=start_timestamp,
                    end_timestamp=end_timestamp,
                )
            except Exception as e:
                if "fts5" in str(e).lower() or "syntax" in str(e).lower():
                    return f'FTS5 query syntax error: {str(e)}\n\nValid examples:\n- Anna AND 电影\n- 电影 OR 音乐\n- "exact phrase"\n- (电影 OR 音乐) AND Anna'
                raise

            # Search conversations by keyword (exclude current session)
            try:
                conversation_results = self.db.search_conversations_by_keyword(
                    query=query if query else None,
                    limit=limit // 2,
                    exclude_session_id=self.session_id,
                    role=role,
                    start_timestamp=start_timestamp,
                    end_timestamp=end_timestamp,
                )
            except Exception as e:
                if "fts5" in str(e).lower() or "syntax" in str(e).lower():
                    return f'FTS5 query syntax error: {str(e)}\n\nValid examples:\n- Anna AND 电影\n- 电影 OR 音乐\n- "exact phrase"\n- (电影 OR 音乐) AND Anna'
                raise

            result = []

            # Add search criteria summary
            criteria = []
            if query:
                criteria.append(f"keywords: '{query}'")
            if role:
                criteria.append(f"role: {role}")
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

            if summary_results:
                result.append("== Related Summaries ==")
                for summary_id, summary, first_ts, last_ts, rank in summary_results:
                    time_str = timestamp_to_str(last_ts, tz=Config.TIMEZONE)
                    result.append(f"[{time_str}] {summary}")

            if conversation_results:
                if result and not result[-1].startswith("=="):
                    result.append("")  # Empty line separator
                result.append("== Related Conversations ==")
                for conv_id, timestamp, conv_role, text, rank in conversation_results:
                    time_str = timestamp_to_str(timestamp, tz=Config.TIMEZONE)
                    role_display = "User" if conv_role == "user" else "Assistant"
                    result.append(f"[{time_str}] {role_display}: {text}")

            if not summary_results and not conversation_results:
                return "No relevant memories found matching the search criteria"

            return "\n".join(result)

        except Exception as e:
            logger.error(f"Memory search failed: {e}", exc_info=True)
            return f"Memory search failed: {str(e)}"
