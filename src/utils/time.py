from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional
import time
import re

from config import Config


def get_current_timestamp() -> int:
    return int(time.time())


def get_current_datetime(tz: Optional[ZoneInfo] = None) -> datetime:
    if tz is None:
        tz = Config.TIMEZONE
    return datetime.now(tz)


def timestamp_to_datetime(timestamp: int, tz: Optional[ZoneInfo] = None) -> datetime:
    if tz is None:
        tz = Config.TIMEZONE
    return datetime.fromtimestamp(timestamp, tz)


def timestamp_to_str(timestamp: int, format_str: str = "%Y-%m-%d %H:%M:%S", tz: Optional[ZoneInfo] = None) -> str:
    dt = timestamp_to_datetime(timestamp, tz)
    return dt.strftime(format_str)


def datetime_to_timestamp(dt: datetime) -> int:
    return int(dt.timestamp())


def format_relative_time(timestamp: int, tz: Optional[ZoneInfo] = None) -> str:
    now = get_current_timestamp()
    diff = now - timestamp
    
    if diff < 60:
        return "just now"
    elif diff < 3600:
        minutes = diff // 60
        return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
    elif diff < 86400:
        hours = diff // 3600
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    elif diff < 604800:
        days = diff // 86400
        return f"{days} day{'s' if days > 1 else ''} ago"
    elif diff < 2592000:
        weeks = diff // 604800
        return f"{weeks} week{'s' if weeks > 1 else ''} ago"
    elif diff < 31536000:
        months = diff // 2592000
        return f"{months} month{'s' if months > 1 else ''} ago"
    else:
        years = diff // 31536000
        return f"{years} year{'s' if years > 1 else ''} ago"


def validate_timestamp(timestamp: int) -> bool:
    min_timestamp = 0
    max_timestamp = get_current_timestamp() + 86400 * 365
    return min_timestamp <= timestamp <= max_timestamp


def parse_time_expression(time_expr: str) -> Optional[int]:
    """Parse a time expression to Unix timestamp
    
    Supports:
    - Unix timestamp: "1234567890"
    - ISO datetime: "2025-01-28T14:30:00"
    - Relative time: "in 2 hours", "in 30m", "tomorrow"
    
    Args:
        time_expr: Time expression string
        
    Returns:
        Unix timestamp or None if invalid
    """
    time_expr = time_expr.strip()
    
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
    
    # Try parsing relative time expressions
    time_expr_lower = time_expr.lower()
    current_time = get_current_timestamp()
    
    # "in X hours/minutes/days"
    match = re.match(r'in\s+(\d+)\s*(s|sec|second|seconds|m|min|minute|minutes|h|hour|hours|d|day|days|w|week|weeks)', time_expr_lower)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        
        if unit in ['s', 'sec', 'second', 'seconds']:
            return current_time + amount
        elif unit in ['m', 'min', 'minute', 'minutes']:
            return current_time + amount * 60
        elif unit in ['h', 'hour', 'hours']:
            return current_time + amount * 3600
        elif unit in ['d', 'day', 'days']:
            return current_time + amount * 86400
        elif unit in ['w', 'week', 'weeks']:
            return current_time + amount * 604800
    
    # Special keywords
    if time_expr_lower == 'tomorrow':
        return current_time + 86400
    elif time_expr_lower == 'next week':
        return current_time + 604800
    
    return None


def format_timestamp(timestamp: int, include_date: bool = True, include_time: bool = True) -> str:
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
