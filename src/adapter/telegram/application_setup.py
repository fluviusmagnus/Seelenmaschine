import asyncio
from typing import Any, Callable, List

from telegram import BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler

from utils.logger import get_logger

logger = get_logger()


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
