"""Telegram Bot Implementation"""

import asyncio
from typing import Optional
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from config import Config
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
        if not self._application:
            logger.error("Cannot send scheduled message: application not initialized")
            return

        try:
            # Step 1: Process scheduled task through LLM
            # This will wrap the message, call LLM, and save the response to memory
            logger.info(f"Processing scheduled task '{task_name}': {message[:50]}...")
            llm_response = await self.message_handler._handle_scheduled_message(
                message, task_name
            )

            # Step 2: Format the LLM response for Telegram HTML
            formatted_response = self.message_handler._format_response_for_telegram(
                llm_response
            )

            # Step 3: Send the LLM response to user
            try:
                await self._application.bot.send_message(
                    chat_id=self.config.TELEGRAM_USER_ID,
                    text=formatted_response,
                    parse_mode="HTML",
                )
                logger.info(
                    f"Scheduled task response sent (HTML): {llm_response[:50]}..."
                )
            except Exception as e:
                # Fallback to plain text if HTML fails
                error_msg = str(e)
                logger.warning(
                    f"HTML parsing failed for scheduled message, sending plain text: {error_msg}"
                )
                await self._application.bot.send_message(
                    chat_id=self.config.TELEGRAM_USER_ID, text=llm_response
                )
                logger.info(
                    f"Scheduled task response sent (plain text): {llm_response[:50]}..."
                )

            # Note: The LLM response is already saved to memory by _process_scheduled_task
            # We don't need to save it again here

        except Exception as e:
            logger.error(
                f"Failed to process/send scheduled message: {e}", exc_info=True
            )
            # Re-raise to let scheduler know it failed
            raise

    def create_application(self) -> None:
        """Create and configure the Telegram application"""
        self._application = (
            Application.builder().token(self.config.TELEGRAM_BOT_TOKEN).build()
        )

        # Add command handlers
        self._application.add_handler(CommandHandler("start", self._cmd_start))
        self._application.add_handler(CommandHandler("help", self._cmd_help))
        self._application.add_handler(
            CommandHandler("new", self.message_handler.handle_new_session)
        )
        self._application.add_handler(
            CommandHandler("reset", self.message_handler.handle_reset_session)
        )

        # Add message handler for regular text messages
        self._application.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND, self.message_handler.handle_message
            )
        )

        # Add post_init hook to start scheduler after bot is ready
        async def post_init(application: Application) -> None:
            """Start scheduler after application initialization"""
            if self._initialized:
                logger.warning("Bot already initialized, skipping post_init")
                return

            # Register bot commands in Telegram menu
            commands = [
                BotCommand("new", "Archive current session and start new"),
                BotCommand("reset", "Delete current session and start fresh"),
                BotCommand("help", "Show help and available commands"),
                BotCommand("start", "Welcome message"),
            ]
            await application.bot.set_my_commands(commands)
            logger.info("Bot commands registered in Telegram menu")

            # Register bot commands in Telegram menu

            # Start scheduler as a background task
            import asyncio

            self.scheduler._task = asyncio.create_task(self.scheduler.run_forever())
            logger.info("Scheduler started as background task")
            self._initialized = True

        # Add post_shutdown hook to stop scheduler gracefully
        async def post_shutdown(application: Application) -> None:
            """Stop scheduler before shutdown"""
            self.scheduler.stop()
            # Wait a bit for scheduler to finish current iteration
            if self.scheduler._task and not self.scheduler._task.done():
                try:
                    await asyncio.wait_for(self.scheduler._task, timeout=2.0)
                except asyncio.TimeoutError:
                    logger.warning("Scheduler did not stop in time")
                except asyncio.CancelledError:
                    pass
            logger.info("Scheduler stopped")

        self._application.post_init = post_init
        self._application.post_shutdown = post_shutdown

        logger.info("Telegram application created and handlers registered")

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
