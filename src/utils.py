import re
from config import Config
from datetime import datetime


def remove_blockquote_tags(text: str) -> str:
    """移除文本中的blockquote标签及其内容,并去除头尾的空白字符

    Args:
        text: 包含blockquote标签的文本

    Returns:
        清理过的文本
    """
    return re.sub(r"<blockquote>.*?</blockquote>\n*", "", text, flags=re.DOTALL).strip()


def now_tz() -> datetime:
    """获取当前时区的时间日期"""
    return datetime.now(Config.TIMEZONE)


def datetime_str(dt: datetime) -> str:
    """格式化完整时间日期"""
    return dt.strftime("%Y-%m-%d %a %H:%M:%S %Z")


def date_str(dt: datetime) -> str:
    """格式化日期"""
    return dt.strftime("%Y-%m-%d %a")


def datetime_to_timestamp(dt: datetime) -> int:
    """转换datetime为UNIX时间戳"""
    return int(dt.timestamp())


def timestamp_to_datetime(ts: int) -> datetime:
    """转换UNIX时间戳为datetime"""
    return datetime.fromtimestamp(ts, Config.TIMEZONE)
