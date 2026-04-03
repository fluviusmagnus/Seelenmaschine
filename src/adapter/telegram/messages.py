from typing import Any

from adapter.telegram.delivery import (
    TelegramAccessGuard,
    TelegramResponseSender,
    typing_indicator,
)
from telegram import Update
from telegram.ext import ContextTypes

from core.approval import ApprovalService
from utils.logger import get_logger

logger = get_logger()


class TelegramMessages:
    """Handle Telegram messages, files, and scheduled callbacks."""

    def __init__(
        self,
        *,
        core_bot: Any,
        access_guard: TelegramAccessGuard,
        approval_service: Any,
        files: Any,
        response_sender: TelegramResponseSender,
        preview_text: Any,
        format_exception_for_user: Any,
        intermediate_callback: Any,
    ):
        self.core_bot = core_bot
        self.access_guard = access_guard
        self.approval_service = approval_service
        self.files = files
        self.response_sender = response_sender
        self.preview_text = preview_text
        self.format_exception_for_user = format_exception_for_user
        self.intermediate_callback = intermediate_callback

    async def _safe_reply_text(self, reply_text: Any, text: str) -> None:
        """Best-effort Telegram reply that never re-raises delivery failures."""
        try:
            await reply_text(text)
        except Exception as send_error:
            logger.error(
                f"Failed to send Telegram reply message: {send_error}",
                exc_info=True,
            )

    async def send_scheduled_message(
        self,
        application: Any,
        message: str,
        task_name: str = "Scheduled Task",
        task_id: str | None = None,
    ) -> None:
        """Process a scheduled task and send the result through the bot."""
        if not application:
            logger.error("Cannot send scheduled message: application not initialized")
            return

        try:
            async with typing_indicator(
                lambda: application.bot.send_chat_action(
                    chat_id=self.core_bot.config.TELEGRAM_USER_ID,
                    action="typing",
                ),
                "Scheduled typing indicator failed",
            ):
                logger.info(
                    f"Processing scheduled task '{task_name}': {message[:50]}..."
                )
                response = await self.process_scheduled_task(message, task_name, task_id)
                await self.response_sender.send_bot_text(
                    telegram_bot=application.bot,
                    chat_id=self.core_bot.config.TELEGRAM_USER_ID,
                    text=response,
                    html_warning_template=(
                        "HTML parsing failed for scheduled segment {index}, "
                        "sending plain text: {error}"
                    ),
                    fatal_error_template=(
                        "Failed to send scheduled segment {index}: {error}"
                    ),
                    preview_text=self.preview_text,
                    debug_prefix="Sent scheduled segment",
                )
                logger.debug(
                    "Scheduled task response sent: " f"{self.preview_text(response)}"
                )
        except Exception as error:
            logger.error(
                f"Failed to process/send scheduled message: {error}",
                exc_info=True,
            )
            raise

    async def handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle regular text messages."""
        if not update.effective_user or not update.message or not update.message.text:
            return

        if await self.access_guard.reject_unauthorized(
            update,
            log_message="Unauthorized message",
        ):
            return

        user_message = update.message.text
        logger.debug(f"Received message: {user_message[:50]}...")

        approval_service = self.approval_service
        if isinstance(approval_service, ApprovalService):
            pending_request = approval_service.abort_pending()
        else:
            pending_request = None

        if pending_request is not None:
            await self._safe_reply_text(
                update.message.reply_text, "❌ Pending action aborted."
            )
            return

        try:
            async with typing_indicator(
                lambda: context.bot.send_chat_action(
                    chat_id=update.effective_chat.id, action="typing"
                ),
                "Typing indicator failed",
            ):
                response = await self.process_message(user_message)
                await self.response_sender.send_reply_text(
                    reply_text=update.message.reply_text,
                    text=response,
                    html_warning_template=(
                        "HTML parsing failed for segment {index}, "
                        "sending as plain text: {error}"
                    ),
                    fatal_error_template="Failed to send segment {index}: {error}",
                    preview_text=self.preview_text,
                    debug_prefix="Sending Telegram text segment",
                )
        except Exception as error:
            logger.error(f"Error handling message: {error}", exc_info=True)
            await self._safe_reply_text(
                update.message.reply_text,
                "Sorry, an error occurred while processing your message.\n\n"
                f"Details: {self.format_exception_for_user(error)}",
            )

    async def handle_file(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        await self.files.handle_file(
            update=update,
            context=context,
            process_message=self.process_message,
            response_sender=self.response_sender,
            preview_text=self.preview_text,
            format_exception_for_user=self.format_exception_for_user,
        )

    async def process_message(self, user_message: str) -> str:
        return await self.core_bot.process_message(
            user_message,
            intermediate_callback=self.intermediate_callback,
        )

    async def process_scheduled_task(
        self,
        task_message: str,
        task_name: str = "Scheduled Task",
        task_id: str | None = None,
    ) -> str:
        return await self.core_bot.process_scheduled_task(
            task_message,
            task_name,
            task_id,
            intermediate_callback=self.intermediate_callback,
        )

    async def process_system_event(self, event_message: str) -> str:
        return await self.core_bot.process_system_event(
            event_message,
            intermediate_callback=self.intermediate_callback,
        )
