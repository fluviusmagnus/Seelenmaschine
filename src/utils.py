import re
from config import Config
from datetime import datetime
import time
import logging
from functools import wraps


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


def performance_monitor(func):
    """性能监控装饰器"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        if not Config.ENABLE_PERFORMANCE_LOGGING:
            return func(*args, **kwargs)

        start_time = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            end_time = time.perf_counter()
            execution_time = end_time - start_time

            logging.info(
                f"性能监控 - {func.__module__}.{func.__name__}: "
                f"执行时间 {execution_time:.4f}s"
            )
            return result
        except Exception as e:
            end_time = time.perf_counter()
            execution_time = end_time - start_time
            logging.error(
                f"性能监控 - {func.__module__}.{func.__name__}: "
                f"执行失败 {execution_time:.4f}s, 错误: {str(e)}"
            )
            raise

    return wrapper


class PerformanceTimer:
    """性能计时器上下文管理器"""

    def __init__(self, operation_name: str):
        self.operation_name = operation_name
        self.start_time = None

    def __enter__(self):
        if Config.ENABLE_PERFORMANCE_LOGGING:
            self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if Config.ENABLE_PERFORMANCE_LOGGING and self.start_time:
            end_time = time.perf_counter()
            execution_time = end_time - self.start_time

            if exc_type is None:
                logging.info(f"性能计时 - {self.operation_name}: {execution_time:.4f}s")
            else:
                logging.error(
                    f"性能计时 - {self.operation_name}: 执行失败 {execution_time:.4f}s, "
                    f"错误: {str(exc_val)}"
                )
