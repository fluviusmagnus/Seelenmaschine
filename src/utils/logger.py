from loguru import logger
import sys
from pathlib import Path
from typing import Optional

from config import Config


def setup_logger(
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    rotation: str = "10 MB",
    retention: str = "7 days",
    compression: str = "zip"
) -> None:
    logger.remove()
    
    level_str = log_level.upper()
    
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level=level_str,
        colorize=True
    )
    
    if log_file:
        log_path = Path(log_file)
        if not log_path.is_absolute():
            log_path = Path.cwd() / log_file
        
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.add(
            log_path,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
            level=level_str,
            rotation=rotation,
            retention=retention,
            compression=compression
        )


def init_logger() -> None:
    log_level = Config.DEBUG_LOG_LEVEL
    log_file = "debug.log" if Config.DEBUG_MODE else None
    
    setup_logger(
        log_level=log_level,
        log_file=log_file
    )
    
    if Config.DEBUG_MODE:
        logger.debug("Debug mode enabled")
        logger.debug(f"Profile: {Config.PROFILE}")
        logger.debug(f"Data directory: {Config.DATA_DIR}")


def get_logger():
    return logger