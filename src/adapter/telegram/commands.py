import html
import json
from typing import Any

from telegram import BotCommand
from telegram import Update
from telegram.ext import ContextTypes

from adapter.telegram.delivery import TelegramAccessGuard
from core.approval import ApprovalService
from utils.logger import get_logger

logger = get_logger()


class TelegramCommands:
    """Handle Telegram command flows and approval messaging."""

    _START_TEXT = (
        "Welcome to Seelenmaschine! 🤖\n\n"
        "I'm your AI companion with long-term memory.\n\n"
        "Commands:\n"
        "/help - Show this help message\n"
        "/new - Start a new session (archives current)\n"
        "/reset - Reset current session\n\n"
        "Just send me a message to start chatting!"
    )
    _HELP_TEXT = (
        "Available commands:\n\n"
        "/start - Welcome message\n"
        "/help - Show this help\n"
        "/new - Archive current session and start new\n"
        "/reset - Delete current session and start fresh\n\n"
        "Features:\n"
        "• Long-term memory across sessions\n"
        "• Vector-based memory retrieval\n"
        "• Scheduled tasks and reminders\n"
        "• Tool integration (MCP, Skills)\n\n"
        "Just chat naturally - I'll remember our conversations!"
    )

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
        return [
            BotCommand("new", "Archive current session and start new"),
            BotCommand("reset", "Delete current session and start fresh"),
            BotCommand("approve", "Approve a pending dangerous action"),
            BotCommand("help", "Show help and available commands"),
            BotCommand("start", "Welcome message"),
        ]

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

        await update.message.reply_text(self._START_TEXT)

    async def handle_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /help command."""
        del context
        if not update.message:
            return
        await update.message.reply_text(self._HELP_TEXT)

    async def handle_new_session(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Archive the current session and start a new one."""
        del context
        if not update.effective_user or not update.message:
            return
        if await self.access_guard.reject_unauthorized(
            update,
            log_message="Unauthorized /new command",
        ):
            return

        try:
            await self.core_bot.create_new_session()
            await update.message.reply_text(
                "✓ New session created! Previous conversations have been summarized and archived.\n\n"
                "I still remember our history and can recall it when relevant."
            )
        except Exception as error:
            logger.error(f"Error creating new session: {error}", exc_info=True)
            await update.message.reply_text("Error creating new session.")

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
            await update.message.reply_text(
                "✓ Session reset! Current conversation has been deleted.\n\n"
                "Starting fresh, but I still have memories from previous sessions."
            )
        except Exception as error:
            logger.error(f"Error resetting session: {error}", exc_info=True)
            await update.message.reply_text("Error resetting session.")

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
        result_preview = html.escape(self.preview_text(result, max_length=300))
        if result.startswith("Error:") or result.startswith("Command failed"):
            prefix = "⚠️ <b>Approved action finished with an error-like result</b>"
        else:
            prefix = "✅ <b>Approved action finished</b>"

        await self._send_status_message(
            (
                f"{prefix}\n\n"
                f"<b>Tool:</b> <code>{html.escape(tool_name)}</code>\n"
                f"<b>Result preview:</b> <pre>{result_preview}</pre>"
            ),
            parse_mode="HTML",
        )

    async def notify_approved_action_failed(
        self, tool_name: str, error: Exception
    ) -> None:
        """Inform the Telegram user that an approved action failed."""
        error_preview = html.escape(self.format_exception_for_user(error))
        await self._send_status_message(
            (
                "❌ <b>Approved action failed unexpectedly</b>\n\n"
                f"<b>Tool:</b> <code>{html.escape(tool_name)}</code>\n"
                f"<b>Error:</b> <pre>{error_preview}</pre>"
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
            await update.message.reply_text("No pending action to approve.")

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
