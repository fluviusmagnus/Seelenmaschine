import json
import re
import time
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Dict, List, Optional

from core.config import Config
from utils.logger import get_logger

logger = get_logger()


class ToolTraceStore:
    """Persist tool execution traces in a profile-local JSONL file."""

    ARGUMENTS_PREVIEW_MAX = Config.TOOL_TRACE_ARGUMENTS_PREVIEW_MAX
    ARGUMENTS_FULL_MAX = Config.TOOL_TRACE_ARGUMENTS_FULL_MAX
    RESULT_PREVIEW_MAX = Config.TOOL_TRACE_RESULT_PREVIEW_MAX
    RESULT_FULL_MAX = Config.TOOL_TRACE_RESULT_FULL_MAX
    MAX_RECORDS = 100
    _BASE64_SEQUENCE_PATTERN = re.compile(r"[A-Za-z0-9+/=]{512,}")

    def __init__(self, data_dir: Path, max_records: int = MAX_RECORDS):
        self.data_dir = Path(data_dir)
        self.file_path = self.data_dir / "tool_traces.jsonl"
        self.max_records = max_records
        self._lock = Lock()
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def append_trace(
        self,
        *,
        trace_id: Optional[int] = None,
        session_id: Optional[int],
        tool_name: str,
        arguments: Dict[str, Any],
        result: Any,
        status: str,
        duration_ms: int,
        approval_required: bool,
        approved_by_user: bool,
    ) -> int:
        """Append one tool execution trace to the JSONL file."""
        timestamp = int(time.time())
        result_text = "" if result is None else str(result)
        arguments_text = self._to_json_text(arguments)
        trace_id = trace_id or time.time_ns()

        record = {
            "trace_id": trace_id,
            "timestamp": timestamp,
            "iso_time": self._timestamp_to_iso(timestamp),
            "session_id": session_id,
            "tool_name": tool_name,
            "status": status,
            "duration_ms": duration_ms,
            "approval_required": approval_required,
            "approved_by_user": approved_by_user,
            "arguments_preview": self._truncate_text(
                arguments_text, Config.TOOL_TRACE_ARGUMENTS_PREVIEW_MAX
            ),
            "arguments_full": self._truncate_text(
                arguments_text, Config.TOOL_TRACE_ARGUMENTS_FULL_MAX
            ),
            "result_preview": self._sanitize_and_truncate_result(
                result_text, Config.TOOL_TRACE_RESULT_PREVIEW_MAX
            ),
            "result_full": self._sanitize_and_truncate_result(
                result_text, Config.TOOL_TRACE_RESULT_FULL_MAX
            ),
            "original_result_length": len(result_text),
            "stored_full_length": len(
                self._sanitize_and_truncate_result(
                    result_text, Config.TOOL_TRACE_RESULT_FULL_MAX
                )
            ),
            "result_truncated": len(result_text)
            > len(
                self._sanitize_and_truncate_result(
                    result_text, Config.TOOL_TRACE_RESULT_FULL_MAX
                )
            ),
        }

        with self._lock:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        return trace_id

    def prune_to_max_records(self) -> None:
        """Keep only the newest N records when the session ends."""
        with self._lock:
            records = self._load_records_unlocked()
            if len(records) <= self.max_records:
                return

            trimmed = records[-self.max_records :]
            with open(self.file_path, "w", encoding="utf-8") as f:
                for record in trimmed:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def query_records(
        self,
        *,
        current_session_id: Optional[int],
        trace_id: Optional[int] = None,
        limit: int = 5,
        tool_name: Optional[str] = None,
        status: Optional[str] = None,
        query: Optional[str] = None,
        since_timestamp: Optional[int] = None,
        until_timestamp: Optional[int] = None,
        current_session_only: bool = True,
        include_full_result: bool = False,
        include_arguments: bool = True,
    ) -> str:
        """Query stored tool traces and format them for LLM consumption."""
        with self._lock:
            records = self._load_records_unlocked()

        if not records:
            return "No tool history records found."

        matched = self._filter_records(
            records,
            current_session_id=current_session_id,
            trace_id=trace_id,
            tool_name=tool_name,
            status=status,
            query=query,
            since_timestamp=since_timestamp,
            until_timestamp=until_timestamp,
            current_session_only=current_session_only,
        )

        if trace_id is None:
            matched = matched[:limit]

        if not matched:
            return "No tool history records matched the query."

        lines: List[str] = [f"Found {len(matched)} tool trace(s).", ""]
        for idx, record in enumerate(matched, start=1):
            lines.append(f"{idx}) trace_id={record.get('trace_id')}")
            lines.append(f"Time: {record.get('iso_time', '')}")
            lines.append(f"Session: {record.get('session_id')}")
            lines.append(f"Tool: {record.get('tool_name', '')}")
            lines.append(f"Status: {record.get('status', '')}")
            lines.append(f"Duration: {record.get('duration_ms', 0)} ms")

            if include_arguments:
                lines.append(
                    f"Arguments preview: {record.get('arguments_preview', '')}"
                )
                if include_full_result:
                    lines.append(f"Arguments full: {record.get('arguments_full', '')}")

            lines.append(f"Result preview: {record.get('result_preview', '')}")
            lines.append(
                f"Has full result: {'yes' if record.get('result_full') else 'no'}"
            )
            lines.append(
                f"Stored full length: {record.get('stored_full_length', 0)} chars"
            )
            lines.append(
                f"Truncated: {'yes' if record.get('result_truncated') else 'no'}"
            )

            if include_full_result:
                lines.append(f"Result full: {record.get('result_full', '')}")

            if idx < len(matched):
                lines.append("")

        return "\n".join(lines)

    def _filter_records(
        self,
        records: List[Dict[str, Any]],
        *,
        current_session_id: Optional[int],
        trace_id: Optional[int],
        tool_name: Optional[str],
        status: Optional[str],
        query: Optional[str],
        since_timestamp: Optional[int],
        until_timestamp: Optional[int],
        current_session_only: bool,
    ) -> List[Dict[str, Any]]:
        matched: List[Dict[str, Any]] = []
        query_lower = query.lower() if query else None

        for record in reversed(records):
            if trace_id is not None:
                if record.get("trace_id") != trace_id:
                    continue
                if current_session_only and current_session_id is not None:
                    if record.get("session_id") != current_session_id:
                        continue
                matched.append(record)
                break

            if current_session_only and current_session_id is not None:
                if record.get("session_id") != current_session_id:
                    continue

            if tool_name and record.get("tool_name") != tool_name:
                continue

            if status and record.get("status") != status:
                continue

            timestamp = record.get("timestamp")
            if since_timestamp is not None and isinstance(timestamp, int):
                if timestamp < since_timestamp:
                    continue
            if until_timestamp is not None and isinstance(timestamp, int):
                if timestamp > until_timestamp:
                    continue

            if query_lower:
                haystacks = [
                    str(record.get("tool_name", "")),
                    str(record.get("arguments_preview", "")),
                    str(record.get("arguments_full", "")),
                    str(record.get("result_preview", "")),
                    str(record.get("result_full", "")),
                ]
                if not any(query_lower in haystack.lower() for haystack in haystacks):
                    continue

            matched.append(record)

        return matched

    def _load_records_unlocked(self) -> List[Dict[str, Any]]:
        if not self.file_path.exists():
            return []

        records: List[Dict[str, Any]] = []
        with open(self.file_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    records.append(json.loads(stripped))
                except json.JSONDecodeError:
                    logger.warning("Skipping invalid tool trace log line")
        return records

    def _sanitize_and_truncate_result(self, text: str, max_length: int) -> str:
        if not text:
            return ""

        base64_match = self._find_base64_like_sequence(text)
        if base64_match is not None:
            text = (
                "[tool output omitted: detected large base64/binary-like payload "
                f"of length ≈ {len(base64_match)}]"
            )

        return self._truncate_text(text, max_length)

    def _truncate_text(self, text: str, max_length: int) -> str:
        if len(text) <= max_length:
            return text
        omitted = len(text) - max_length
        return f"{text[:max_length]}...[truncated {omitted} chars]"

    def _find_base64_like_sequence(self, text: str) -> Optional[str]:
        for match in self._BASE64_SEQUENCE_PATTERN.finditer(text):
            candidate = match.group(0)
            if self._looks_like_base64_payload(candidate):
                return candidate
        return None

    def _looks_like_base64_payload(self, candidate: str) -> bool:
        if len(candidate) < 512:
            return False
        if not any(ch in candidate for ch in "+/="):
            return False
        return len(set(candidate)) >= 8

    def _to_json_text(self, value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except Exception:
            return str(value)

    def _timestamp_to_iso(self, timestamp: int) -> str:
        return time.strftime(
            "%Y-%m-%dT%H:%M:%S%z",
            time.localtime(timestamp),
        )


class ToolTraceQueryTool:
    """Tool for LLM to query recent tool execution history."""

    def __init__(
        self,
        store: ToolTraceStore,
        session_id_provider: Callable[[], Optional[int]],
    ):
        self._store = store
        self._session_id_provider = session_id_provider

    @property
    def name(self) -> str:
        return "query_tool_history"

    @property
    def description(self) -> str:
        return (
            "Query recent tool execution history. By default it returns the latest "
            "records from the current session in reverse chronological order. Use "
            "include_full_result=true only when the preview is insufficient."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "trace_id": {
                    "type": "integer",
                    "description": "Exact trace ID to fetch. If provided, it takes precedence over list filters.",
                },
                "limit": {
                    "type": "integer",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20,
                    "description": "Maximum number of records to return when listing traces.",
                },
                "tool_name": {
                    "type": "string",
                    "description": "Filter by tool name.",
                },
                "status": {
                    "type": "string",
                    "enum": ["success", "error", "rejected"],
                    "description": "Filter by execution status.",
                },
                "query": {
                    "type": "string",
                    "description": "Simple text match against tool name, arguments, and stored results.",
                },
                "since_timestamp": {
                    "type": "integer",
                    "description": "Only include traces whose timestamp is >= this Unix timestamp.",
                },
                "until_timestamp": {
                    "type": "integer",
                    "description": "Only include traces whose timestamp is <= this Unix timestamp.",
                },
                "current_session_only": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to limit results to the current session by default.",
                },
                "include_full_result": {
                    "type": "boolean",
                    "default": False,
                    "description": "Whether to include stored full result text instead of only previews.",
                },
                "include_arguments": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to include arguments preview/full in the response.",
                },
            },
            "required": [],
        }

    async def execute(
        self,
        trace_id: Optional[int] = None,
        limit: int = 5,
        tool_name: Optional[str] = None,
        status: Optional[str] = None,
        query: Optional[str] = None,
        since_timestamp: Optional[int] = None,
        until_timestamp: Optional[int] = None,
        current_session_only: bool = True,
        include_full_result: bool = False,
        include_arguments: bool = True,
    ) -> str:
        current_session_id = None
        if current_session_only:
            try:
                current_session_id = self._session_id_provider()
            except Exception as e:
                logger.warning(
                    f"Failed to resolve current session for tool history query: {e}"
                )

        return self._store.query_records(
            current_session_id=current_session_id,
            trace_id=trace_id,
            limit=limit,
            tool_name=tool_name,
            status=status,
            query=query,
            since_timestamp=since_timestamp,
            until_timestamp=until_timestamp,
            current_session_only=current_session_only,
            include_full_result=include_full_result,
            include_arguments=include_arguments,
        )
