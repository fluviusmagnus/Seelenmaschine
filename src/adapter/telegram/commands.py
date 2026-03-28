from typing import Any

from telegram import BotCommand
from telegram import Update
from telegram.ext import ContextTypes

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

    def __init__(self, handler: Any):
        self.handler = handler

    @staticmethod
    def _is_authorized(update: Update, telegram_user_id: int) -> bool:
        """Check whether the Telegram update comes from the configured user."""
        return bool(
            update.effective_user
            and update.message
            and update.effective_user.id == telegram_user_id
        )

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
        user_id = update.effective_user.id
        if user_id != self.handler.core_bot.config.TELEGRAM_USER_ID:
            await update.message.reply_text("Unauthorized access.")
            logger.warning(f"Unauthorized access attempt from user {user_id}")
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
        if not self._is_authorized(
            update, self.handler.core_bot.config.TELEGRAM_USER_ID
        ):
            await update.message.reply_text("Unauthorized access.")
            return

        try:
            await self.handler.core_bot.create_new_session()
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
        if not self._is_authorized(
            update, self.handler.core_bot.config.TELEGRAM_USER_ID
        ):
            await update.message.reply_text("Unauthorized access.")
            return

        try:
            self.handler.core_bot.reset_session()
            await update.message.reply_text(
                "✓ Session reset! Current conversation has been deleted.\n\n"
                "Starting fresh, but I still have memories from previous sessions."
            )
        except Exception as error:
            logger.error(f"Error resetting session: {error}", exc_info=True)
            await update.message.reply_text("Error resetting session.")
