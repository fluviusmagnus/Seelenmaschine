"""Telegram Bot Implementation"""

from typing import Optional
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from core.config import Config
from adapter.telegram.application_setup import TelegramApplicationSetup
from adapter.telegram.scheduled_sender import ScheduledMessageSender
from utils.logger import get_logger

logger = get_logger()


class TelegramBot:
    """Telegram Bot with scheduled task support"""

    def __init__(self, message_handler):
        """Initialize Telegram bot

        Args:
            message_handler: MessageHandler instance for processing messages
        """
        self.config = Config()
        self.message_handler = message_handler
        self._application: Optional[Application] = None
        self._initialized = False

        # Use the scheduler from message_handler
        self.scheduler = message_handler.scheduler
        self._scheduled_sender = ScheduledMessageSender(
            config=self.config,
            message_handler=message_handler,
        )
        self._application_setup = TelegramApplicationSetup(self)

        # Override callback for scheduler to send messages via Telegram
        self.scheduler.set_message_callback(self._send_scheduled_message)

    async def _send_scheduled_message(
        self, message: str, task_name: str = "Scheduled Task"
    ) -> None:
        """Send a scheduled message to the user - triggers LLM conversation

        This is called by the scheduler when a task triggers. Unlike the old
        implementation that sent the raw task message, this version:
        1. Passes the task message to message_handler for LLM processing
        2. LLM generates a contextual response based on the task
        3. Sends the LLM response to the user
        4. LLM response is saved to memory (task message itself is not saved)

        Args:
            message: Raw task message from scheduler
            task_name: Name of the scheduled task for context
        """
        await self._scheduled_sender.send_scheduled_message(
            application=self._application,
            message=message,
            task_name=task_name,
        )

    def create_application(self) -> None:
        """Create and configure the Telegram application"""
        self._application = self._application_setup.create_application(
            application_builder_factory=Application.builder,
            command_handler_cls=CommandHandler,
            message_handler_cls=MessageHandler,
            filters_module=filters,
        )

    async def _cmd_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /start command"""
        user_id = update.effective_user.id

        # Check if user is authorized
        if user_id != self.config.TELEGRAM_USER_ID:
            await update.message.reply_text("Unauthorized access.")
            logger.warning(f"Unauthorized access attempt from user {user_id}")
            return

        await update.message.reply_text(
            "Welcome to Seelenmaschine! 🤖\n\n"
            "I'm your AI companion with long-term memory.\n\n"
            "Commands:\n"
            "/help - Show this help message\n"
            "/new - Start a new session (archives current)\n"
            "/reset - Reset current session\n\n"
            "Just send me a message to start chatting!"
        )

    async def _cmd_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /help command"""
        await update.message.reply_text(
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

    def run(self) -> None:
        """Start the bot"""
        if not self._application:
            raise RuntimeError(
                "Application not created. Call create_application() first."
            )

        logger.info("Starting Telegram bot with scheduler...")

        # Run the bot (scheduler runs as a background job and will be stopped by post_shutdown)
        self._application.run_polling(allowed_updates=Update.ALL_TYPES)

        logger.info("Bot stopped")

    def stop(self) -> None:
        """Stop the bot application"""
        if self._application and self._application.running:
            logger.info("Stopping Telegram bot...")
            self._application.stop()

