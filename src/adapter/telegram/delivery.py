"""Shared Telegram delivery helpers for typing indicators and segmented sends."""

import asyncio
import random
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from utils.logger import get_logger

logger = get_logger()


@asynccontextmanager
async def typing_indicator(
    send_action: Callable[[], Awaitable[None]],
    warning_message: str,
) -> AsyncIterator[None]:
    """Maintain a best-effort typing indicator while work is in progress."""

    async def _keep_typing_indicator() -> None:
        while True:
            try:
                await send_action()
                await asyncio.sleep(3)
            except Exception as error:
                logger.warning(f"{warning_message}: {error}")
                await asyncio.sleep(3)

    typing_task = asyncio.create_task(_keep_typing_indicator())
    try:
        yield
    finally:
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass


async def send_segmented_text(
    *,
    segments: list[str],
    send_html: Callable[[str], Awaitable[Any]],
    send_plain: Callable[[str], Awaitable[Any]],
    html_warning_template: str,
    fatal_error_template: Optional[str] = None,
    preview_text: Optional[Callable[[str, int], str]] = None,
    debug_prefix: Optional[str] = None,
) -> None:
    """Send segmented text with HTML-first delivery and plain-text fallback."""
    for index, segment in enumerate(segments):
        try:
            if preview_text and debug_prefix:
                logger.debug(
                    f"{debug_prefix} {index + 1}/{len(segments)}: "
                    f"{preview_text(segment)}"
                )
            await send_html(segment)
            if index < len(segments) - 1:
                await asyncio.sleep(random.uniform(1.0, 2.0))
        except Exception as error:
            logger.warning(html_warning_template.format(index=index + 1, error=error))
            try:
                await send_plain(segment)
            except Exception as fallback_error:
                if fatal_error_template:
                    logger.error(
                        fatal_error_template.format(
                            index=index + 1,
                            error=fallback_error,
                        )
                    )
                else:
                    raise
