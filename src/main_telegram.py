#!/usr/bin/env python3
import asyncio
import sys
from pathlib import Path

# Add project root to path for absolute imports
sys.path.insert(0, str(Path(__file__).parent.parent))  # project root

from adapter.telegram.adapter import TelegramAdapter
from adapter.telegram.controller import TelegramController
from core.bot import CoreBot
from core.config import init_config
from core.runtime import SchedulerRuntime, register_stop_signal_handlers
from utils.logger import init_logger


def _build_post_init(
    *, core_bot: CoreBot, scheduler_runtime: SchedulerRuntime
):
    """Build startup hook that warms tools before starting other background work."""

    scheduler_post_init = scheduler_runtime.build_post_init()

    async def post_init(application):
        await core_bot.warmup_tool_runtime()
        await scheduler_post_init(application)

    return post_init


def main():
    if len(sys.argv) < 2:
        print("Usage: python main_telegram.py <profile>")
        sys.exit(1)

    profile = sys.argv[1]
    init_config(profile)
    init_logger()
    core_bot = CoreBot()
    message_handler = TelegramController(core_bot=core_bot)
    adapter = TelegramAdapter(message_handler=message_handler)
    scheduler_runtime = SchedulerRuntime(core_bot.scheduler)
    adapter.create_application(
        post_init=_build_post_init(
            core_bot=core_bot,
            scheduler_runtime=scheduler_runtime,
        ),
        post_shutdown=scheduler_runtime.build_post_shutdown(),
    )
    register_stop_signal_handlers(adapter.stop)
    adapter.run()


if __name__ == "__main__":
    main()
