#!/usr/bin/env python3
import sys
from pathlib import Path

# Add project root to path for absolute imports
sys.path.insert(0, str(Path(__file__).parent.parent))  # project root

from adapter.telegram.app import build_telegram_bot, register_signal_handlers
from adapter.telegram.bot import TelegramBot
from adapter.telegram.handlers import MessageHandler


def main():
    if len(sys.argv) < 2:
        print("Usage: python main_telegram.py <profile>")
        sys.exit(1)

    profile = sys.argv[1]
    bot = build_telegram_bot(
        profile=profile,
        message_handler_cls=MessageHandler,
        telegram_bot_cls=TelegramBot,
    )
    register_signal_handlers(bot)
    bot.run()


if __name__ == "__main__":
    main()
