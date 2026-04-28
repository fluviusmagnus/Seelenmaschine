from typing import Any

from telegram import BotCommand
from telegram import Update
from telegram.ext import ContextTypes

from adapter.telegram.delivery import TelegramAccessGuard, typing_indicator
from core.hitl import ApprovalService
from texts import ApprovalTexts, TelegramTexts
from utils.logger import get_logger

logger = get_logger()


class TelegramCommands:
    """Handle Telegram command flows and approval messaging."""

    def __init__(
        self,
        *,
        core_bot: Any,
        access_guard: TelegramAccessGuard,
        approval_service: ApprovalService,
        get_telegram_bot: Any,
        preview_text: Any,
        format_exception_for_user: Any,
    ):
        self.core_bot = core_bot
        self.access_guard = access_guard
        self.approval_service = approval_service
        self.get_telegram_bot = get_telegram_bot
        self.preview_text = preview_text
        self.format_exception_for_user = format_exception_for_user

    @classmethod
    def build_menu_commands(cls) -> list[BotCommand]:
        """Return the Telegram command menu definition."""
        return [BotCommand(name, description) for name, description in TelegramTexts.MENU_COMMANDS]

    async def handle_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /start command."""
        del context
        if not update.effective_user or not update.message:
            return
        if await self.access_guard.reject_unauthorized(
            update,
            log_message="Unauthorized access attempt from /start",
        ):
            return

        await update.message.reply_text(TelegramTexts.START)

    async def handle_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /help command."""
        del context
        if not update.message:
            return
        await update.message.reply_text(TelegramTexts.HELP)

    async def handle_new_session(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Archive the current session and start a new one."""
        if not update.effective_user or not update.message:
            return
        if await self.access_guard.reject_unauthorized(
            update,
            log_message="Unauthorized /new command",
        ):
            return

        try:
            async with typing_indicator(
                lambda: context.bot.send_chat_action(
                    chat_id=update.effective_chat.id, action="typing"
                ),
                "Typing indicator failed during /new",
            ):
                await self.core_bot.create_new_session()
                await update.message.reply_text(TelegramTexts.NEW_SESSION_SUCCESS)
        except Exception as error:
            logger.error(f"Error creating new session: {error}", exc_info=True)
            await update.message.reply_text(
                TelegramTexts.operation_error(
                    "Error creating new session",
                    self.format_exception_for_user(error),
                )
            )

    async def handle_reset_session(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Delete the current session and start fresh."""
        del context
        if not update.effective_user or not update.message:
            return
        if await self.access_guard.reject_unauthorized(
            update,
            log_message="Unauthorized /reset command",
        ):
            return

        try:
            self.core_bot.reset_session()
            await update.message.reply_text(TelegramTexts.RESET_SESSION_SUCCESS)
        except Exception as error:
            logger.error(f"Error resetting session: {error}", exc_info=True)
            await update.message.reply_text(
                TelegramTexts.operation_error(
                    "Error resetting session",
                    self.format_exception_for_user(error),
                )
            )

    async def request_approval(
        self, tool_name: str, arguments: dict, reason: str
    ) -> bool:
        """Send an approval request to Telegram and wait for the user's decision."""

        async def _send_approval_message(text: str, parse_mode: str | None) -> None:
            telegram_bot = self.get_telegram_bot()
            if telegram_bot is None:
                return

            kwargs: dict[str, Any] = {
                "chat_id": self.core_bot.config.TELEGRAM_USER_ID,
                "text": text,
            }
            if parse_mode:
                kwargs["parse_mode"] = parse_mode
            await telegram_bot.send_message(**kwargs)

        return await self.approval_service.request_approval(
            tool_name,
            arguments,
            reason,
            send_message=_send_approval_message,
            timeout_seconds=600.0,
        )

    async def notify_approved_action_finished(
        self, tool_name: str, result: str
    ) -> None:
        """Inform the Telegram user that an approved action finished."""
        await self._send_status_message(
            ApprovalTexts.approved_action_finished(
                tool_name=tool_name,
                result_preview=self.preview_text(result, max_length=300),
                error_like=result.startswith("Error:")
                or result.startswith("Command failed"),
            ),
            parse_mode="HTML",
        )

    async def notify_approved_action_failed(
        self, tool_name: str, error: Exception
    ) -> None:
        """Inform the Telegram user that an approved action failed."""
        await self._send_status_message(
            ApprovalTexts.approved_action_failed(
                tool_name=tool_name,
                error_preview=self.format_exception_for_user(error),
            ),
            parse_mode="HTML",
        )

    async def handle_approve(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Approve the current pending dangerous action."""
        del context
        if not update.effective_user or not update.message:
            return
        if await self.access_guard.reject_unauthorized(
            update,
            log_message="Unauthorized /approve command",
        ):
            return

        pending_request = self.approval_service.approve_pending()
        if pending_request is None:
            await update.message.reply_text(TelegramTexts.NO_PENDING_ACTION)

    async def handle_stop(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Stop the current running tool loop and abort any pending approval."""
        del context
        if not update.effective_user or not update.message:
            return
        if await self.access_guard.reject_unauthorized(
            update,
            log_message="Unauthorized /stop command",
        ):
            return

        stop_reason = ApprovalTexts.STOP_ALL_FURTHER_REASON
        pending_request = self.approval_service.abort_pending(stop_reason)
        stop_requested = self.core_bot.request_stop_current_run(stop_reason)

        if pending_request is not None or stop_requested:
            await update.message.reply_text(TelegramTexts.STOP_SIGNAL_SENT)
            return

        await update.message.reply_text(TelegramTexts.NO_RUNNING_TOOL_LOOP)

    async def _send_status_message(
        self, text: str, parse_mode: str | None = None
    ) -> None:
        """Send a best-effort Telegram status notification."""
        telegram_bot = self.get_telegram_bot()
        if telegram_bot is None:
            return

        try:
            kwargs: dict[str, Any] = {
                "chat_id": self.core_bot.config.TELEGRAM_USER_ID,
                "text": text,
            }
            if parse_mode:
                kwargs["parse_mode"] = parse_mode
            await telegram_bot.send_message(**kwargs)
        except Exception as error:
            logger.warning(f"Failed to send status message: {error}")
