"""Application runtime helpers owned by core."""

import asyncio
import signal
from typing import Any, Callable, Optional

from telegram.ext import Application

from utils.logger import get_logger

logger = get_logger()


class SchedulerRuntime:
    """Own scheduler lifecycle independently from the Telegram adapter."""

    def __init__(self, scheduler: Any):
        self.scheduler = scheduler
        self._initialized = False

    def build_post_init(self) -> Callable[[Application], Any]:
        """Return the application post-init hook that starts the scheduler."""

        async def post_init(_application: Application) -> None:
            if self._initialized:
                logger.warning("Runtime already initialized, skipping post_init")
                return

            self.scheduler._task = asyncio.create_task(self.scheduler.run_forever())
            logger.info("Scheduler started as background task")
            self._initialized = True

        return post_init

    def build_post_shutdown(self) -> Callable[[Application], Any]:
        """Return the application post-shutdown hook that stops the scheduler."""

        async def post_shutdown(_application: Application) -> None:
            self.scheduler.stop()
            if self.scheduler._task and not self.scheduler._task.done():
                try:
                    await asyncio.wait_for(self.scheduler._task, timeout=2.0)
                except asyncio.TimeoutError:
                    logger.warning("Scheduler did not stop in time")
                except asyncio.CancelledError:
                    pass
            logger.info("Scheduler stopped")

        return post_shutdown


def register_stop_signal_handlers(
    stop_callback: Callable[[], None],
    signal_fn: Callable[[int, Callable[..., Optional[None]]], Any] = signal.signal,
) -> None:
    """Register SIGINT/SIGTERM handlers that stop the runtime gracefully."""

    def _stop_runtime(_sig: int, _frame: Any) -> None:
        stop_callback()

    signal_fn(signal.SIGINT, _stop_runtime)
    signal_fn(signal.SIGTERM, _stop_runtime)
