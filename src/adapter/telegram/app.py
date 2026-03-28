import signal
from typing import Any, Callable, Optional, Type

from core.config import init_config
from utils.logger import get_logger

logger = get_logger()


def build_telegram_bot(
    profile: str,
    message_handler_cls: Type[Any],
    telegram_bot_cls: Type[Any],
    init_config_fn: Callable[[str], None] = init_config,
) -> Any:
    """Initialize config and build the Telegram bot."""
    init_config_fn(profile)
    logger.info(f"Starting Seelenmaschine with profile: {profile}")

    message_handler = message_handler_cls()
    bot = telegram_bot_cls(message_handler=message_handler)
    bot.create_application()
    return bot


def register_signal_handlers(
    bot: Any,
    signal_fn: Callable[[int, Callable[..., Optional[None]]], Any] = signal.signal,
) -> None:
    """Register SIGINT/SIGTERM handlers that stop the bot gracefully."""

    def _stop_bot(_sig: int, _frame: Any) -> None:
        if hasattr(bot, "stop"):
            bot.stop()

    signal_fn(signal.SIGINT, _stop_bot)
    signal_fn(signal.SIGTERM, _stop_bot)

