#!/usr/bin/env python3
import sys
import signal
from pathlib import Path

# Add project root to path for absolute imports
sys.path.insert(0, str(Path(__file__).parent.parent))  # project root

from config import init_config
from tg_bot.bot import TelegramBot
from tg_bot.handlers import MessageHandler
from utils.logger import get_logger

logger = get_logger()


def main():
    if len(sys.argv) < 2:
        print("Usage: python main_telegram.py <profile>")
        sys.exit(1)

    profile = sys.argv[1]
    init_config(profile)

    logger.info(f"Starting Seelenmaschine with profile: {profile}")

    message_handler = MessageHandler()

    bot = TelegramBot(message_handler=message_handler)
    bot.create_application()

    # Signal handlers use stop() method which is public API
    signal.signal(
        signal.SIGINT, lambda sig, frame: bot.stop() if hasattr(bot, "stop") else None
    )
    signal.signal(
        signal.SIGTERM, lambda sig, frame: bot.stop() if hasattr(bot, "stop") else None
    )

    bot.run()


if __name__ == "__main__":
    main()
