from typing import Dict, Any
from datetime import datetime, timedelta

from core.database import DatabaseManager
from utils.time import timestamp_to_str
from core.config import Config
from prompts.runtime import load_seele_json
from texts import ToolTexts
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
        self.embedding_client = embedding_client
        self.reranker_client = reranker_client
        self._disabled = False

    @property
    def name(self) -> str:
        return "search_memories"

    @property
    def description(self) -> str:
        return ToolTexts.MemorySearch.DESCRIPTION

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": ToolTexts.MemorySearch.PARAMETER_DESCRIPTIONS["query"],
                },
                "limit": {
                    "type": "integer",
                    "description": ToolTexts.MemorySearch.PARAMETER_DESCRIPTIONS["limit"],
                    "default": 10,
                },
                "role": {
                    "type": "string",
                    "enum": ["user", "assistant"],
                    "description": ToolTexts.MemorySearch.PARAMETER_DESCRIPTIONS["role"],
                },
                "time_period": {
                    "type": "string",
                    "enum": ["last_day", "last_week", "last_month", "last_year"],
                    "description": ToolTexts.MemorySearch.PARAMETER_DESCRIPTIONS["time_period"],
                },
                "start_date": {
                    "type": "string",
                    "description": ToolTexts.MemorySearch.PARAMETER_DESCRIPTIONS["start_date"],
                },
                "end_date": {
                    "type": "string",
                    "description": ToolTexts.MemorySearch.PARAMETER_DESCRIPTIONS["end_date"],
                },
                "include_current_session": {
                    "type": "boolean",
                    "description": ToolTexts.MemorySearch.PARAMETER_DESCRIPTIONS["include_current_session"],
                    "default": False,
                },
                "session_id": {
                    "type": "integer",
                    "description": ToolTexts.MemorySearch.PARAMETER_DESCRIPTIONS["session_id"],
                },
                "search_target": {
                    "type": "string",
                    "enum": ["all", "summaries", "conversations"],
                    "description": ToolTexts.MemorySearch.PARAMETER_DESCRIPTIONS["search_target"],
                    "default": "all",
                },
                "search_mode": {
                    "type": "string",
                    "enum": ["keyword", "vector", "hybrid"],
                    "description": ToolTexts.MemorySearch.PARAMETER_DESCRIPTIONS["search_mode"],
                    "default": "hybrid",
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
        return ToolTexts.MemorySearch.fts_syntax_error(details)

    @staticmethod
    def _invalid_query_message(error_msg: str) -> str:
        """Build a consistent validation error message for bad queries."""
        return ToolTexts.MemorySearch.invalid_query(error_msg)

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
        search_mode: str,
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
        if search_mode != "hybrid":
            criteria.append(f"mode: {search_mode}")
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

    @staticmethod
    def _looks_like_natural_language_query(query: str) -> bool:
        """Heuristically detect longer natural-language style queries."""
        if not query:
            return False

        operators = {"AND", "OR", "NOT", "(", ")", '"'}
        if any(operator in query for operator in operators):
            return False

        return len(query) >= 12 or len(query.split()) >= 3

    async def _get_query_embedding(self, query: str) -> list[float] | None:
        """Get an embedding for vector-assisted fallback if available."""
        if not self.embedding_client or not query:
            return None

        get_embedding_async = getattr(self.embedding_client, "get_embedding_async", None)
        if not callable(get_embedding_async):
            return None
        return await get_embedding_async(query)

    async def _maybe_add_vector_summary_results(
        self,
        summary_results: list[tuple[Any, ...]],
        *,
        query: str,
        limit: int,
        search_target: str,
        force_vector: bool = False,
        session_id: int | None = None,
        exclude_session_id: int | None = None,
        start_timestamp: int | None = None,
        end_timestamp: int | None = None,
        query_embedding: list[float] | None = None,
    ) -> list[tuple[Any, ...]]:
        """Supplement sparse keyword summary results with vector-retrieved summaries."""
        if search_target not in {"all", "summaries"}:
            return summary_results

        if not force_vector and not self._looks_like_natural_language_query(query):
            return summary_results

        target_limit = limit if search_target == "summaries" else max(1, limit // 2)
        if len(summary_results) >= target_limit:
            return summary_results

        embedding = query_embedding if query_embedding is not None else await self._get_query_embedding(query)
        if embedding is None:
            return summary_results

        exclude_ids = [row[0] for row in summary_results]
        candidate_limit = min(max(target_limit * 2, target_limit + 2), 20)
        vector_results = self.db.search_summaries(
            embedding,
            limit=candidate_limit,
            exclude_ids=exclude_ids or None,
            session_id=session_id,
            exclude_session_id=exclude_session_id,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        )
        if not vector_results:
            return summary_results

        combined = list(summary_results)
        combined.extend(vector_results)
        return combined

    async def _maybe_add_vector_conversation_results(
        self,
        conversation_results: list[tuple[Any, ...]],
        *,
        query: str,
        limit: int,
        search_target: str,
        session_id: int | None,
        exclude_session_id: int | None,
        exclude_recent_from_session_id: int | None,
        exclude_recent_limit: int,
        role: str | None,
        start_timestamp: int | None,
        end_timestamp: int | None,
        force_vector: bool = False,
        query_embedding: list[float] | None = None,
    ) -> list[tuple[Any, ...]]:
        """Supplement sparse keyword conversation results with vector-retrieved conversations."""
        if search_target not in {"all", "conversations"}:
            return conversation_results
        if not force_vector and not self._looks_like_natural_language_query(query):
            return conversation_results

        target_limit = limit if search_target == "conversations" else max(1, limit // 2)
        if len(conversation_results) >= target_limit:
            return conversation_results

        embedding = query_embedding if query_embedding is not None else await self._get_query_embedding(query)
        if embedding is None:
            return conversation_results

        exclude_ids = [row[0] for row in conversation_results]
        candidate_limit = min(max(target_limit * 2, target_limit + 2), 20)
        vector_results = self.db.search_conversations(
            embedding,
            limit=candidate_limit,
            exclude_ids=exclude_ids or None,
            session_id=session_id,
            exclude_session_id=exclude_session_id,
            exclude_recent_from_session_id=exclude_recent_from_session_id,
            exclude_recent_limit=exclude_recent_limit,
            role=role,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        )
        if not vector_results:
            return conversation_results

        combined = list(conversation_results)
        combined.extend(vector_results)
        return combined

    @staticmethod
    def _summary_vector_similarity(rank: float) -> float:
        """Convert stored rank/distance into a bounded similarity-like score."""
        if rank is None or rank <= 0:
            return 0.0
        return 1.0 / (1.0 + max(float(rank), 0.0))

    @staticmethod
    def _summary_keyword_features(
        summary_text: str,
        *,
        lowered_query: str,
        query_tokens: list[str],
        rank: float,
    ) -> tuple[float, float, float, float]:
        """Extract simple keyword-oriented features for weighted fusion."""
        summary_lower = str(summary_text).lower()
        exact_match = 1.0 if lowered_query and lowered_query in summary_lower else 0.0
        token_coverage = 0.0
        if query_tokens:
            matched = sum(1 for token in query_tokens if token and token in summary_lower)
            token_coverage = matched / max(len(query_tokens), 1)

        lexical_overlap = 0.0
        if lowered_query:
            query_units = DatabaseManager._extract_search_units(lowered_query)
            if query_units:
                matched_units = sum(
                    1 for unit in query_units if unit and unit in summary_lower
                )
                lexical_overlap = matched_units / max(len(query_units), 1)

        keyword_origin = 1.0 if rank is not None and rank <= 0 else 0.0
        return keyword_origin, token_coverage, exact_match, lexical_overlap

    @staticmethod
    def _normalized_recency(last_ts: int, *, min_ts: int, max_ts: int) -> float:
        """Normalize recency into a 0..1 score."""
        if max_ts <= min_ts:
            return 1.0
        return (int(last_ts) - min_ts) / (max_ts - min_ts)

    @staticmethod
    def _sort_summary_results(
        summary_results: list[tuple[Any, ...]],
        *,
        query: str,
        limit: int | None = None,
    ) -> list[tuple[Any, ...]]:
        """Apply weighted fusion across keyword, vector, and recency signals."""
        if not summary_results:
            return summary_results

        lowered_query = (query or "").lower()
        query_tokens = [token for token in lowered_query.split() if token not in {"and", "or", "not"}]

        last_timestamps = [int(row[4]) for row in summary_results]
        min_ts = min(last_timestamps)
        max_ts = max(last_timestamps)

        def score(row: tuple[Any, ...]) -> tuple[float, float, float, float, int]:
            _summary_id, _session_id, summary, _first_ts, last_ts, rank = row
            keyword_origin, token_coverage, exact_match, lexical_overlap = (
                MemorySearchTool._summary_keyword_features(
                    summary,
                    lowered_query=lowered_query,
                    query_tokens=query_tokens,
                    rank=rank,
                )
            )
            vector_similarity = MemorySearchTool._summary_vector_similarity(rank)
            recency = MemorySearchTool._normalized_recency(
                int(last_ts),
                min_ts=min_ts,
                max_ts=max_ts,
            )

            fusion_score = (
                0.22 * keyword_origin
                + 0.18 * token_coverage
                + 0.18 * exact_match
                + 0.32 * lexical_overlap
                + 0.28 * vector_similarity
                + 0.05 * recency
            )
            return (
                fusion_score,
                lexical_overlap,
                exact_match,
                token_coverage,
                int(last_ts),
            )

        sorted_results = sorted(summary_results, key=score, reverse=True)
        if limit is not None:
            return sorted_results[:limit]
        return sorted_results

    @staticmethod
    def _conversation_keyword_features(
        conversation_text: str,
        *,
        lowered_query: str,
        query_tokens: list[str],
        rank: float,
    ) -> tuple[float, float, float, float]:
        """Extract keyword-oriented features for conversation fusion ranking."""
        text_lower = str(conversation_text).lower()
        exact_match = 1.0 if lowered_query and lowered_query in text_lower else 0.0
        token_coverage = 0.0
        if query_tokens:
            matched = sum(1 for token in query_tokens if token and token in text_lower)
            token_coverage = matched / max(len(query_tokens), 1)

        lexical_overlap = 0.0
        if lowered_query:
            query_units = DatabaseManager._extract_search_units(lowered_query)
            if query_units:
                matched_units = sum(1 for unit in query_units if unit and unit in text_lower)
                lexical_overlap = matched_units / max(len(query_units), 1)

        keyword_origin = 1.0 if rank is not None and rank <= 0 else 0.0
        return keyword_origin, token_coverage, exact_match, lexical_overlap

    @staticmethod
    def _sort_conversation_results(
        conversation_results: list[tuple[Any, ...]],
        *,
        query: str,
        limit: int | None = None,
    ) -> list[tuple[Any, ...]]:
        """Apply weighted fusion across keyword, vector, and recency for conversations."""
        if not conversation_results:
            return conversation_results

        lowered_query = (query or "").lower()
        query_tokens = [token for token in lowered_query.split() if token not in {"and", "or", "not"}]

        timestamps = [int(row[2]) for row in conversation_results]
        min_ts = min(timestamps)
        max_ts = max(timestamps)

        def score(row: tuple[Any, ...]) -> tuple[float, float, float, float, int]:
            _conv_id, _session_id, timestamp, _role, text, rank = row
            keyword_origin, token_coverage, exact_match, lexical_overlap = (
                MemorySearchTool._conversation_keyword_features(
                    text,
                    lowered_query=lowered_query,
                    query_tokens=query_tokens,
                    rank=rank,
                )
            )
            vector_similarity = MemorySearchTool._summary_vector_similarity(rank)
            recency = MemorySearchTool._normalized_recency(int(timestamp), min_ts=min_ts, max_ts=max_ts)
            fusion_score = (
                0.22 * keyword_origin
                + 0.18 * token_coverage
                + 0.18 * exact_match
                + 0.32 * lexical_overlap
                + 0.28 * vector_similarity
                + 0.05 * recency
            )
            return (fusion_score, lexical_overlap, exact_match, token_coverage, int(timestamp))

        sorted_results = sorted(conversation_results, key=score, reverse=True)
        if limit is not None:
            return sorted_results[:limit]
        return sorted_results

    async def _maybe_rerank_conversation_results(
        self,
        conversation_results: list[tuple[Any, ...]],
        *,
        query: str,
        limit: int,
        search_target: str,
    ) -> list[tuple[Any, ...]]:
        """Optionally rerank top conversation candidates with an external reranker."""
        if search_target not in {"all", "conversations"}:
            return conversation_results
        if not query or len(conversation_results) < 2 or not self.reranker_client:
            return conversation_results

        is_enabled = getattr(self.reranker_client, "is_enabled", None)
        if callable(is_enabled) and not is_enabled():
            return conversation_results

        target_limit = limit if search_target == "conversations" else max(1, limit // 2)
        candidate_limit = min(len(conversation_results), max(target_limit * 2, target_limit + 2), 12)
        candidates = conversation_results[:candidate_limit]
        documents = [{"text": row[4], "row_index": index} for index, row in enumerate(candidates)]

        rerank_async = getattr(self.reranker_client, "rerank_async", None)
        if not callable(rerank_async):
            return conversation_results
        reranked_docs = await rerank_async(query, documents, top_n=min(target_limit, len(documents)))

        if not reranked_docs:
            return conversation_results

        reranked_indices = [doc.get("row_index") for doc in reranked_docs if doc.get("row_index") is not None]
        seen_indices = set()
        reranked_rows = []
        for row_index in reranked_indices:
            if row_index in seen_indices or not (0 <= row_index < len(candidates)):
                continue
            reranked_rows.append(candidates[row_index])
            seen_indices.add(row_index)

        if not reranked_rows:
            return conversation_results

        remaining_candidates = [row for index, row in enumerate(candidates) if index not in seen_indices]
        tail = conversation_results[candidate_limit:]
        return reranked_rows + remaining_candidates + tail

    async def _maybe_rerank_summary_results(
        self,
        summary_results: list[tuple[Any, ...]],
        *,
        query: str,
        limit: int,
        search_target: str,
    ) -> list[tuple[Any, ...]]:
        """Optionally rerank top summary candidates with an external reranker."""
        if search_target not in {"all", "summaries"}:
            return summary_results
        if not query or len(summary_results) < 2 or not self.reranker_client:
            return summary_results

        is_enabled = getattr(self.reranker_client, "is_enabled", None)
        if callable(is_enabled) and not is_enabled():
            return summary_results

        target_limit = limit if search_target == "summaries" else max(1, limit // 2)
        candidate_limit = min(len(summary_results), max(target_limit * 2, target_limit + 2), 12)
        candidates = summary_results[:candidate_limit]
        documents = [
            {
                "text": row[2],
                "row_index": index,
            }
            for index, row in enumerate(candidates)
        ]

        rerank_async = getattr(self.reranker_client, "rerank_async", None)
        if not callable(rerank_async):
            return summary_results
        reranked_docs = await rerank_async(query, documents, top_n=min(target_limit, len(documents)))

        if not reranked_docs:
            return summary_results

        reranked_indices = [
            doc.get("row_index") for doc in reranked_docs if doc.get("row_index") is not None
        ]
        seen_indices = set()
        reranked_rows = []
        for row_index in reranked_indices:
            if row_index in seen_indices or not (0 <= row_index < len(candidates)):
                continue
            reranked_rows.append(candidates[row_index])
            seen_indices.add(row_index)

        if not reranked_rows:
            return summary_results

        remaining_candidates = [
            row for index, row in enumerate(candidates) if index not in seen_indices
        ]
        tail = summary_results[candidate_limit:]
        return reranked_rows + remaining_candidates + tail

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
        search_mode: str = "hybrid",
    ) -> str:
        """Execute memory search with keyword, vector, or hybrid recall."""
        if self._disabled:
            return "Memory search is disabled during response generation to prevent recursion"

        try:
            if search_mode not in {"keyword", "vector", "hybrid"}:
                return "Invalid search_mode. Use one of: keyword, vector, hybrid"

            if search_mode == "vector" and not query:
                return "search_mode='vector' requires query"

            # Sanitize query to fix FTS5 issues with dates in keyword-capable modes.
            if query and search_mode in {"keyword", "hybrid"}:
                query = self._sanitize_query(query)

            # Validate query syntax for keyword-capable modes.
            if query and search_mode in {"keyword", "hybrid"}:
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
            shared_query_embedding = None
            should_use_vector = query and search_mode in {"vector", "hybrid"}
            if should_use_vector:
                shared_query_embedding = await self._get_query_embedding(query)

            if search_target in {"all", "summaries"}:
                if search_mode in {"keyword", "hybrid"}:
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
                if should_use_vector:
                    summary_results = await self._maybe_add_vector_summary_results(
                        summary_results,
                        query=query,
                        limit=limit,
                        search_target=search_target,
                        force_vector=True,
                        session_id=effective_session_id,
                        exclude_session_id=exclude_session_id,
                        start_timestamp=start_timestamp,
                        end_timestamp=end_timestamp,
                        query_embedding=shared_query_embedding,
                    )
                summary_results = self._sort_summary_results(
                    summary_results,
                    query=query,
                )
                summary_results = await self._maybe_rerank_summary_results(
                    summary_results,
                    query=query,
                    limit=limit,
                    search_target=search_target,
                )
                summary_results = summary_results[
                    : (limit if search_target == "summaries" else limit // 2)
                ]

            if search_target in {"all", "conversations"}:
                if search_mode in {"keyword", "hybrid"}:
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
                if should_use_vector:
                    conversation_results = await self._maybe_add_vector_conversation_results(
                        conversation_results,
                        query=query,
                        limit=limit,
                        search_target=search_target,
                        session_id=effective_session_id,
                        exclude_session_id=exclude_session_id,
                        exclude_recent_from_session_id=exclude_recent_from_session_id,
                        exclude_recent_limit=exclude_recent_limit,
                        role=role,
                        start_timestamp=start_timestamp,
                        end_timestamp=end_timestamp,
                        force_vector=True,
                        query_embedding=shared_query_embedding,
                    )
                conversation_results = self._sort_conversation_results(
                    conversation_results,
                    query=query,
                )
                conversation_results = await self._maybe_rerank_conversation_results(
                    conversation_results,
                    query=query,
                    limit=limit,
                    search_target=search_target,
                )
                conversation_results = conversation_results[
                    : (limit if search_target == "conversations" else limit // 2)
                ]

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
                search_mode=search_mode,
            )
            self._append_summary_results(result, summary_results)
            self._append_conversation_results(result, conversation_results)

            if not summary_results and not conversation_results:
                return "No relevant memories found matching the search criteria"

            return "\n".join(result)

        except Exception as e:
            logger.error(f"Memory search failed: {e}", exc_info=True)
            return f"Memory search failed: {str(e)}"
