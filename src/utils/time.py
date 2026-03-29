import re
import time
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from core.config import Config

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 60 * SECONDS_PER_MINUTE
SECONDS_PER_DAY = 24 * SECONDS_PER_HOUR
SECONDS_PER_WEEK = 7 * SECONDS_PER_DAY
SECONDS_PER_MONTH = 30 * SECONDS_PER_DAY
SECONDS_PER_YEAR = 365 * SECONDS_PER_DAY

_SHORT_DURATION_PATTERN = re.compile(r"^(\d+)\s*(s|m|h|d|w)$")
_RELATIVE_DURATION_PATTERN = re.compile(
    r"^in\s+(\d+)\s*"
    r"(s|sec|second|seconds|m|min|minute|minutes|h|hour|hours|d|day|days|w|week|weeks)$"
)
_SECONDS_BY_UNIT = {
    "s": 1,
    "sec": 1,
    "second": 1,
    "seconds": 1,
    "m": SECONDS_PER_MINUTE,
    "min": SECONDS_PER_MINUTE,
    "minute": SECONDS_PER_MINUTE,
    "minutes": SECONDS_PER_MINUTE,
    "h": SECONDS_PER_HOUR,
    "hour": SECONDS_PER_HOUR,
    "hours": SECONDS_PER_HOUR,
    "d": SECONDS_PER_DAY,
    "day": SECONDS_PER_DAY,
    "days": SECONDS_PER_DAY,
    "w": SECONDS_PER_WEEK,
    "week": SECONDS_PER_WEEK,
    "weeks": SECONDS_PER_WEEK,
}
_RELATIVE_TIME_UNITS = (
    (SECONDS_PER_YEAR, "year"),
    (SECONDS_PER_MONTH, "month"),
    (SECONDS_PER_WEEK, "week"),
    (SECONDS_PER_DAY, "day"),
    (SECONDS_PER_HOUR, "hour"),
    (SECONDS_PER_MINUTE, "minute"),
)
_DURATION_OUTPUT_UNITS = (
    (SECONDS_PER_WEEK, "w"),
    (SECONDS_PER_DAY, "d"),
    (SECONDS_PER_HOUR, "h"),
    (SECONDS_PER_MINUTE, "m"),
)
_SPECIAL_TIME_EXPRESSIONS = {
    "tomorrow": SECONDS_PER_DAY,
    "next week": SECONDS_PER_WEEK,
}


def _resolve_timezone(tz: Optional[ZoneInfo] = None) -> ZoneInfo:
    return Config.TIMEZONE if tz is None else tz


def get_current_timestamp() -> int:
    return int(time.time())


def get_current_datetime(tz: Optional[ZoneInfo] = None) -> datetime:
    return datetime.now(_resolve_timezone(tz))


def timestamp_to_datetime(timestamp: int, tz: Optional[ZoneInfo] = None) -> datetime:
    return datetime.fromtimestamp(timestamp, _resolve_timezone(tz))


def timestamp_to_str(
    timestamp: int, format_str: str = "%Y-%m-%d %H:%M:%S", tz: Optional[ZoneInfo] = None
) -> str:
    dt = timestamp_to_datetime(timestamp, tz)
    return dt.strftime(format_str)


def format_current_time_str(tz: Optional[ZoneInfo] = None) -> str:
    """Format the current time as a timezone-aware prompt-friendly string."""
    current_time = get_current_datetime(tz)
    return current_time.strftime("%Y-%m-%d %H:%M:%S %Z")


def format_timestamp_range(
    start_timestamp: int,
    end_timestamp: int,
    tz: Optional[ZoneInfo] = None,
    format_str: str = "%Y-%m-%d %H:%M:%S",
) -> tuple[str, str]:
    """Format a timestamp range using a shared timezone and format."""
    return (
        timestamp_to_str(start_timestamp, format_str=format_str, tz=tz),
        timestamp_to_str(end_timestamp, format_str=format_str, tz=tz),
    )


def datetime_to_timestamp(dt: datetime) -> int:
    return int(dt.timestamp())


def format_relative_time(timestamp: int, tz: Optional[ZoneInfo] = None) -> str:
    now = get_current_timestamp()
    diff = now - timestamp

    if diff < SECONDS_PER_MINUTE:
        return "just now"
    for unit_seconds, unit_name in _RELATIVE_TIME_UNITS:
        if diff >= unit_seconds:
            amount = diff // unit_seconds
            suffix = "s" if amount > 1 else ""
            return f"{amount} {unit_name}{suffix} ago"
    return "just now"


def validate_timestamp(timestamp: int) -> bool:
    min_timestamp = 0
    max_timestamp = get_current_timestamp() + SECONDS_PER_YEAR
    return min_timestamp <= timestamp <= max_timestamp


def parse_duration_to_seconds(time_expr: str) -> Optional[int]:
    """Parse a compact duration like '30s' or '2h' into seconds."""
    normalized_expr = time_expr.strip().lower()
    match = _SHORT_DURATION_PATTERN.match(normalized_expr)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        return amount * _SECONDS_BY_UNIT[unit]

    try:
        return int(normalized_expr)
    except ValueError:
        return None


def format_duration_seconds(seconds: int) -> str:
    """Format seconds as the shortest whole-unit duration string."""
    for unit_seconds, suffix in _DURATION_OUTPUT_UNITS:
        if seconds % unit_seconds == 0:
            return f"{seconds // unit_seconds}{suffix}"
    return f"{seconds}s"


def parse_time_expression(time_expr: str) -> Optional[int]:
    """Parse a time expression to Unix timestamp

    Supports:
    - Unix timestamp: "1234567890"
    - ISO datetime: "2025-01-28T14:30:00"
    - Relative time: "in 2 hours", "in 30m", "3m", "180s", "tomorrow"
    - Simple duration: "30s", "5m", "2h", "1d", "1w"

    Args:
        time_expr: Time expression string

    Returns:
        Unix timestamp or None if invalid
    """
    time_expr = time_expr.strip()
    time_expr_lower = time_expr.lower()
    current_time = get_current_timestamp()

    # Try parsing as unix timestamp
    try:
        timestamp = int(time_expr)
        if validate_timestamp(timestamp):
            return timestamp
    except ValueError:
        pass

    # Try parsing as ISO datetime
    try:
        dt = datetime.fromisoformat(time_expr)
        # If no timezone, assume local timezone
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=Config.TIMEZONE)
        return datetime_to_timestamp(dt)
    except ValueError:
        pass

    # Try parsing simple duration format (e.g., "30s", "5m", "2h", "1d", "1w")
    # This must come before the "in X" pattern to match first.
    duration_seconds = parse_duration_to_seconds(time_expr_lower)
    if duration_seconds is not None and _SHORT_DURATION_PATTERN.match(time_expr_lower):
        return current_time + duration_seconds

    # "in X hours/minutes/days" format
    match = _RELATIVE_DURATION_PATTERN.match(time_expr_lower)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        return current_time + amount * _SECONDS_BY_UNIT[unit]

    if time_expr_lower in _SPECIAL_TIME_EXPRESSIONS:
        return current_time + _SPECIAL_TIME_EXPRESSIONS[time_expr_lower]

    return None


def format_timestamp(
    timestamp: int, include_date: bool = True, include_time: bool = True
) -> str:
    """Format timestamp to human-readable string

    Args:
        timestamp: Unix timestamp
        include_date: Whether to include date
        include_time: Whether to include time

    Returns:
        Formatted string
    """
    if not timestamp:
        return "N/A"

    if include_date and include_time:
        return timestamp_to_str(timestamp, "%Y-%m-%d %H:%M:%S")
    elif include_date:
        return timestamp_to_str(timestamp, "%Y-%m-%d")
    elif include_time:
        return timestamp_to_str(timestamp, "%H:%M:%S")
    else:
        return str(timestamp)

