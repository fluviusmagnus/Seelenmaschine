import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch
import time

from utils.time import (
    get_current_timestamp,
    get_current_datetime,
    timestamp_to_datetime,
    timestamp_to_str,
    datetime_to_timestamp,
    format_relative_time,
    validate_timestamp,
    parse_time_expression,
    format_timestamp,
)


class TestGetCurrentTimestamp:
    """Test get_current_timestamp function."""

    def test_returns_int(self):
        """Test that get_current_timestamp returns an integer."""
        timestamp = get_current_timestamp()
        assert isinstance(timestamp, int)

    def test_is_current_time(self):
        """Test that timestamp is close to current time."""
        timestamp = get_current_timestamp()
        expected = int(time.time())
        assert abs(timestamp - expected) < 2


class TestGetCurrentDatetime:
    """Test get_current_datetime function."""

    def test_returns_datetime(self):
        """Test that get_current_datetime returns a datetime."""
        dt = get_current_datetime()
        assert isinstance(dt, datetime)

    def test_uses_default_timezone(self):
        """Test that it uses default timezone from Config."""
        with patch("utils.time.Config") as mock_config:
            mock_config.TIMEZONE = ZoneInfo("UTC")
            dt = get_current_datetime()
            assert dt.tzinfo == ZoneInfo("UTC")

    def test_uses_custom_timezone(self):
        """Test that it uses custom timezone."""
        tz = ZoneInfo("Asia/Shanghai")
        dt = get_current_datetime(tz=tz)
        assert dt.tzinfo == tz


class TestTimestampToDatetime:
    """Test timestamp_to_datetime function."""

    def test_returns_datetime(self):
        """Test that it returns a datetime."""
        timestamp = 1234567890
        dt = timestamp_to_datetime(timestamp)
        assert isinstance(dt, datetime)

    def test_correct_conversion(self):
        """Test correct timestamp to datetime conversion."""
        timestamp = 1234567890
        dt = timestamp_to_datetime(timestamp, tz=ZoneInfo("UTC"))
        assert dt.year == 2009
        assert dt.month == 2
        assert dt.day == 13

    def test_uses_default_timezone(self):
        """Test that it uses default timezone from Config."""
        with patch("utils.time.Config") as mock_config:
            mock_config.TIMEZONE = ZoneInfo("UTC")
            dt = timestamp_to_datetime(1234567890)
            assert dt.tzinfo == ZoneInfo("UTC")

    def test_uses_custom_timezone(self):
        """Test that it uses custom timezone."""
        tz = ZoneInfo("Asia/Shanghai")
        dt = timestamp_to_datetime(1234567890, tz=tz)
        assert dt.tzinfo == tz


class TestTimestampToStr:
    """Test timestamp_to_str function."""

    def test_returns_string(self):
        """Test that it returns a string."""
        result = timestamp_to_str(1234567890)
        assert isinstance(result, str)

    def test_default_format(self):
        """Test default format string."""
        result = timestamp_to_str(1234567890, tz=ZoneInfo("UTC"))
        assert "2009-02-13" in result
        assert "23:31:30" in result

    def test_custom_format(self):
        """Test custom format string."""
        result = timestamp_to_str(1234567890, format_str="%Y-%m-%d", tz=ZoneInfo("UTC"))
        assert result == "2009-02-13"


class TestDatetimeToTimestamp:
    """Test datetime_to_timestamp function."""

    def test_returns_int(self):
        """Test that it returns an integer."""
        dt = datetime(2009, 2, 13, 23, 31, 30, tzinfo=ZoneInfo("UTC"))
        timestamp = datetime_to_timestamp(dt)
        assert isinstance(timestamp, int)

    def test_correct_conversion(self):
        """Test correct datetime to timestamp conversion."""
        dt = datetime(2009, 2, 13, 23, 31, 30, tzinfo=ZoneInfo("UTC"))
        timestamp = datetime_to_timestamp(dt)
        assert timestamp == 1234567890


class TestFormatRelativeTime:
    """Test format_relative_time function."""

    def test_just_now(self):
        """Test 'just now' for very recent timestamps."""
        current = get_current_timestamp()
        result = format_relative_time(current)
        assert result == "just now"

    def test_minutes_ago(self):
        """Test 'X minutes ago'."""
        current = get_current_timestamp()
        result = format_relative_time(current - 60)
        assert result == "1 minute ago"
        result = format_relative_time(current - 180)
        assert result == "3 minutes ago"

    def test_hours_ago(self):
        """Test 'X hours ago'."""
        current = get_current_timestamp()
        result = format_relative_time(current - 3600)
        assert result == "1 hour ago"
        result = format_relative_time(current - 7200)
        assert result == "2 hours ago"

    def test_days_ago(self):
        """Test 'X days ago'."""
        current = get_current_timestamp()
        result = format_relative_time(current - 86400)
        assert result == "1 day ago"
        result = format_relative_time(current - 172800)
        assert result == "2 days ago"

    def test_weeks_ago(self):
        """Test 'X weeks ago'."""
        current = get_current_timestamp()
        result = format_relative_time(current - 604800)
        assert result == "1 week ago"
        result = format_relative_time(current - 1209600)
        assert result == "2 weeks ago"

    def test_months_ago(self):
        """Test 'X months ago'."""
        current = get_current_timestamp()
        result = format_relative_time(current - 2592000)
        assert result == "1 month ago"
        result = format_relative_time(current - 5184000)
        assert result == "2 months ago"

    def test_years_ago(self):
        """Test 'X years ago'."""
        current = get_current_timestamp()
        result = format_relative_time(current - 31536000)
        assert result == "1 year ago"
        result = format_relative_time(current - 63072000)
        assert result == "2 years ago"


class TestValidateTimestamp:
    """Test validate_timestamp function."""

    def test_valid_current_timestamp(self):
        """Test validation of current timestamp."""
        current = get_current_timestamp()
        assert validate_timestamp(current) is True

    def test_valid_past_timestamp(self):
        """Test validation of past timestamp."""
        assert validate_timestamp(1234567890) is True

    def test_valid_future_timestamp_within_limit(self):
        """Test validation of reasonable future timestamp."""
        current = get_current_timestamp()
        assert validate_timestamp(current + 86400 * 30) is True

    def test_invalid_too_old_timestamp(self):
        """Test validation of too old timestamp."""
        assert validate_timestamp(-1) is False
        assert validate_timestamp(0) is True

    def test_invalid_too_far_future_timestamp(self):
        """Test validation of too far future timestamp."""
        current = get_current_timestamp()
        assert validate_timestamp(current + 86400 * 400) is False


class TestParseTimeExpression:
    """Test parse_time_expression function."""

    def test_unix_timestamp(self):
        """Test parsing Unix timestamp."""
        result = parse_time_expression("1234567890")
        assert result == 1234567890

    def test_iso_datetime(self):
        """Test parsing ISO datetime."""
        result = parse_time_expression("2009-02-13T23:31:30")
        assert result is not None
        assert isinstance(result, int)

    def test_relative_time_seconds(self):
        """Test parsing relative time in seconds."""
        current = get_current_timestamp()
        result = parse_time_expression("in 30 seconds")
        assert result == current + 30

    def test_relative_time_minutes(self):
        """Test parsing relative time in minutes."""
        current = get_current_timestamp()
        result = parse_time_expression("in 5 minutes")
        assert result == current + 300

    def test_relative_time_hours(self):
        """Test parsing relative time in hours."""
        current = get_current_timestamp()
        result = parse_time_expression("in 2 hours")
        assert result == current + 7200

    def test_relative_time_days(self):
        """Test parsing relative time in days."""
        current = get_current_timestamp()
        result = parse_time_expression("in 3 days")
        assert result == current + 259200

    def test_relative_time_weeks(self):
        """Test parsing relative time in weeks."""
        current = get_current_timestamp()
        result = parse_time_expression("in 1 week")
        assert result == current + 604800

    def test_short_units(self):
        """Test parsing short unit abbreviations."""
        current = get_current_timestamp()
        assert parse_time_expression("in 30s") == current + 30
        assert parse_time_expression("in 5m") == current + 300
        assert parse_time_expression("in 2h") == current + 7200
        assert parse_time_expression("in 3d") == current + 259200
        assert parse_time_expression("in 1w") == current + 604800

    def test_tomorrow(self):
        """Test parsing 'tomorrow'."""
        current = get_current_timestamp()
        result = parse_time_expression("tomorrow")
        assert result == current + 86400

    def test_next_week(self):
        """Test parsing 'next week'."""
        current = get_current_timestamp()
        result = parse_time_expression("next week")
        assert result == current + 604800

    def test_invalid_expression(self):
        """Test parsing invalid expression."""
        result = parse_time_expression("invalid time expression")
        assert result is None

    def test_whitespace_handling(self):
        """Test whitespace handling."""
        current = get_current_timestamp()
        result1 = parse_time_expression("in 5 minutes")
        result2 = parse_time_expression("  in  5  minutes  ")
        assert result1 == result2


class TestFormatTimestamp:
    """Test format_timestamp function."""

    def test_zero_timestamp(self):
        """Test' formatting zero timestamp."""
        result = format_timestamp(0)
        assert result == "N/A"

    def test_none_timestamp(self):
        """Test formatting None timestamp."""
        result = format_timestamp(None)
        assert result == "N/A"

    def test_date_and_time(self):
        """Test formatting with both date and time."""
        result = format_timestamp(1234567890, include_date=True, include_time=True)
        assert (
            "2009-02-14" in result
        )  # Note: 1234567890 is 2009-02-13 23:31:30 UTC, but may be 2009-02-14 in local timezone
        assert "07:31:30" in result

    def test_date_only(self):
        """Test formatting with date only."""
        result = format_timestamp(1234567890, include_date=True, include_time=False)
        assert (
            "2009-02-14" in result
        )  # Note: may be 2009-02-13 or 2009-02-14 depending on timezone

    def test_time_only(self):
        """Test formatting with time only."""
        result = format_timestamp(1234567890, include_date=False, include_time=True)
        assert "07:31:30" in result  # Note: may vary depending on timezone

    def test_neither(self):
        """Test formatting with neither date nor time."""
        result = format_timestamp(1234567890, include_date=False, include_time=False)
        assert result == "1234567890"
