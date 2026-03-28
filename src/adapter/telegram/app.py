import asyncio
import signal
from typing import Any, Callable, List, Optional, Type

from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from core.config import Config, init_config
from adapter.telegram.scheduled_sender import ScheduledMessageSender
from utils.logger import get_logger

logger = get_logger()


class TelegramBot:
    """Telegram Bot with scheduled task support."""

    def __init__(self, message_handler: Any):
        self.config = Config()
        self.message_handler = message_handler
        self._application: Optional[Application] = None
        self._initialized = False
        self.scheduler = message_handler.scheduler
        self._scheduled_sender = ScheduledMessageSender(
            config=self.config,
            message_handler=message_handler,
        )
        self._application_setup = TelegramApplicationSetup(self)
        self.scheduler.set_message_callback(self._send_scheduled_message)

    async def _send_scheduled_message(
        self, message: str, task_name: str = "Scheduled Task"
    ) -> None:
        """Send a scheduled message to the user via the LLM flow."""
        await self._scheduled_sender.send_scheduled_message(
            application=self._application,
            message=message,
            task_name=task_name,
        )

    def create_application(self) -> None:
        """Create and configure the Telegram application."""
        self._application = self._application_setup.create_application(
            application_builder_factory=Application.builder,
            command_handler_cls=CommandHandler,
            message_handler_cls=MessageHandler,
            filters_module=filters,
        )

    async def _cmd_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /start command."""
        del context
        user_id = update.effective_user.id
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
        """Handle /help command."""
        del context
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
        """Start the bot."""
        if not self._application:
            raise RuntimeError(
                "Application not created. Call create_application() first."
            )

        logger.info("Starting Telegram bot with scheduler...")
        self._application.run_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("Bot stopped")

    def stop(self) -> None:
        """Stop the bot application."""
        if self._application and self._application.running:
            logger.info("Stopping Telegram bot...")
            self._application.stop()


def build_telegram_bot(
    profile: str,
    message_handler_cls: Type[Any],
    telegram_bot_cls: Type[Any],
    init_config_fn: Callable[[str], None] = init_config,
) -> Any:
    """Initialize config and build the Telegram bot."""
    init_config_fn(profile)
    logger.info(f"Starting Seelenmaschine with profile: {profile}")

    message_handler = message_handler_cls()
    bot = telegram_bot_cls(message_handler=message_handler)
    bot.create_application()
    return bot


def register_signal_handlers(
    bot: Any,
    signal_fn: Callable[[int, Callable[..., Optional[None]]], Any] = signal.signal,
) -> None:
    """Register SIGINT/SIGTERM handlers that stop the bot gracefully."""

    def _stop_bot(_sig: int, _frame: Any) -> None:
        if hasattr(bot, "stop"):
            bot.stop()

    signal_fn(signal.SIGINT, _stop_bot)
    signal_fn(signal.SIGTERM, _stop_bot)


class TelegramApplicationSetup:
    """Create Telegram applications, register handlers, and wire lifecycle hooks."""

    def __init__(self, telegram_bot: Any):
        self.telegram_bot = telegram_bot

    def create_application(
        self,
        application_builder_factory: Callable[[], Any],
        command_handler_cls: type[CommandHandler],
        message_handler_cls: type[MessageHandler],
        filters_module: Any,
    ) -> Application:
        """Build and configure the Telegram application."""
        builder = application_builder_factory().token(
            self.telegram_bot.config.TELEGRAM_BOT_TOKEN
        )
        builder = builder.concurrent_updates(True)
        application = builder.build()
        self.telegram_bot.message_handler.set_telegram_bot(application.bot)

        logger.info(
            "Telegram application created with concurrent update processing enabled"
        )

        for handler in self._build_handlers(
            command_handler_cls=command_handler_cls,
            message_handler_cls=message_handler_cls,
            filters_module=filters_module,
        ):
            application.add_handler(handler)

        application.post_init = self._build_post_init_hook()
        application.post_shutdown = self._build_post_shutdown_hook()

        logger.info("Telegram application created and handlers registered")
        return application

    def _build_handlers(
        self,
        command_handler_cls: type[CommandHandler],
        message_handler_cls: type[MessageHandler],
        filters_module: Any,
    ) -> List[Any]:
        """Build command and message handlers for the Telegram app."""
        return [
            command_handler_cls("start", self.telegram_bot._cmd_start),
            command_handler_cls("help", self.telegram_bot._cmd_help),
            command_handler_cls("new", self.telegram_bot.message_handler.handle_new_session),
            command_handler_cls(
                "reset", self.telegram_bot.message_handler.handle_reset_session
            ),
            command_handler_cls(
                "approve", self.telegram_bot.message_handler.handle_approve
            ),
            message_handler_cls(
                filters_module.TEXT & ~filters_module.COMMAND,
                self.telegram_bot.message_handler.handle_message,
            ),
            message_handler_cls(
                filters_module.Document.ALL
                | filters_module.PHOTO
                | filters_module.VIDEO
                | filters_module.AUDIO
                | filters_module.VOICE,
                self.telegram_bot.message_handler.handle_file,
            ),
        ]

    def _build_post_init_hook(self) -> Callable[[Application], Any]:
        """Build the post_init hook for command registration and scheduler startup."""

        async def post_init(application: Application) -> None:
            if self.telegram_bot._initialized:
                logger.warning("Bot already initialized, skipping post_init")
                return

            commands = [
                BotCommand("new", "Archive current session and start new"),
                BotCommand("reset", "Delete current session and start fresh"),
                BotCommand("approve", "Approve a pending dangerous action"),
                BotCommand("help", "Show help and available commands"),
                BotCommand("start", "Welcome message"),
            ]
            await application.bot.set_my_commands(commands)
            logger.info("Bot commands registered in Telegram menu")

            self.telegram_bot.scheduler._task = asyncio.create_task(
                self.telegram_bot.scheduler.run_forever()
            )
            logger.info("Scheduler started as background task")
            self.telegram_bot._initialized = True

        return post_init

    def _build_post_shutdown_hook(self) -> Callable[[Application], Any]:
        """Build the post_shutdown hook for graceful scheduler shutdown."""

        async def post_shutdown(_application: Application) -> None:
            self.telegram_bot.scheduler.stop()
            if (
                self.telegram_bot.scheduler._task
                and not self.telegram_bot.scheduler._task.done()
            ):
                try:
                    await asyncio.wait_for(self.telegram_bot.scheduler._task, timeout=2.0)
                except asyncio.TimeoutError:
                    logger.warning("Scheduler did not stop in time")
                except asyncio.CancelledError:
                    pass
            logger.info("Scheduler stopped")

        return post_shutdown

