"""Shared Telegram delivery helpers, access checks, and reply pipeline."""

import asyncio
import random
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from telegram import Update

from core.config import Config
from adapter.telegram.formatter import TelegramResponseFormatter
from texts import TelegramTexts
from utils.logger import get_logger

logger = get_logger()


class TelegramAccessGuard:
    """Shared authorization checks for Telegram updates."""

    def __init__(self, config: Any):
        self.config = config

    def is_authorized_user_id(self, user_id: int | None) -> bool:
        """Return whether the provided Telegram user id is allowed."""
        return bool(user_id and user_id == self.config.TELEGRAM_USER_ID)

    def is_authorized_update(self, update: Update) -> bool:
        """Return whether an update comes from the configured Telegram user."""
        user = getattr(update, "effective_user", None)
        return self.is_authorized_user_id(getattr(user, "id", None))

    async def reject_unauthorized(
        self,
        update: Update,
        *,
        log_message: str,
    ) -> bool:
        """Reply with a standard unauthorized message when needed."""
        if self.is_authorized_update(update):
            return False

        message = getattr(update, "message", None)
        if message is not None:
            await message.reply_text(TelegramTexts.UNAUTHORIZED_ACCESS)

        user = getattr(update, "effective_user", None)
        logger.warning(f"{log_message}: user_id={getattr(user, 'id', None)}")
        return True


class TelegramResponseSender:
    """Format, split, and deliver Telegram responses consistently."""

    def __init__(self, *, config: Any, formatter: TelegramResponseFormatter):
        self.config = config
        self.formatter = formatter

    def format_response(self, text: str) -> str:
        """Format assistant text for Telegram HTML delivery."""
        return self.formatter.format_response(text, debug_mode=self.config.DEBUG_MODE)

    def split_message_into_segments(
        self, text: str, max_length: int = Config.TELEGRAM_MESSAGE_MAX_LENGTH
    ) -> list[str]:
        """Split formatted Telegram text into safe segments."""
        return self.formatter.split_message_into_segments(text, max_length=max_length)

    async def send_text(
        self,
        *,
        text: str,
        send_html: Callable[[str], Awaitable[Any]],
        send_plain: Callable[[str], Awaitable[Any]],
        html_warning_template: str,
        fatal_error_template: Optional[str] = None,
        preview_text: Optional[Callable[[str, int], str]] = None,
        debug_prefix: Optional[str] = None,
    ) -> None:
        """Format and send text through the shared segmented delivery pipeline."""
        formatted = self.format_response(text)
        segments = self.split_message_into_segments(formatted)
        logger.info(f"Sending {len(segments)} Telegram segment(s)")
        await send_segmented_text(
            segments=segments,
            send_html=send_html,
            send_plain=send_plain,
            html_warning_template=html_warning_template,
            fatal_error_template=fatal_error_template,
            preview_text=preview_text,
            debug_prefix=debug_prefix,
        )

    async def send_reply_text(
        self,
        *,
        reply_text: Callable[..., Awaitable[Any]],
        text: str,
        html_warning_template: str,
        fatal_error_template: Optional[str] = None,
        preview_text: Optional[Callable[[str, int], str]] = None,
        debug_prefix: Optional[str] = None,
    ) -> None:
        """Send a formatted reply via Update.message.reply_text."""
        await self.send_text(
            text=text,
            send_html=lambda segment: reply_text(segment, parse_mode="HTML"),
            send_plain=reply_text,
            html_warning_template=html_warning_template,
            fatal_error_template=fatal_error_template,
            preview_text=preview_text,
            debug_prefix=debug_prefix,
        )

    async def send_bot_text(
        self,
        *,
        telegram_bot: Any,
        chat_id: int,
        text: str,
        html_warning_template: str,
        fatal_error_template: Optional[str] = None,
        preview_text: Optional[Callable[[str, int], str]] = None,
        debug_prefix: Optional[str] = None,
    ) -> None:
        """Send a formatted proactive Telegram bot message."""
        await self.send_text(
            text=text,
            send_html=lambda segment: telegram_bot.send_message(
                chat_id=chat_id,
                text=segment,
                parse_mode="HTML",
            ),
            send_plain=lambda segment: telegram_bot.send_message(
                chat_id=chat_id,
                text=segment,
            ),
            html_warning_template=html_warning_template,
            fatal_error_template=fatal_error_template,
            preview_text=preview_text,
            debug_prefix=debug_prefix,
        )


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
