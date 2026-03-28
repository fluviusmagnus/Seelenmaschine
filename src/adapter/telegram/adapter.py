import asyncio
import signal
from typing import Any, Callable, List, Optional

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from adapter.telegram.commands import TelegramCommands
from adapter.telegram.scheduled_sender import ScheduledMessageSender
from core.config import Config
from utils.logger import get_logger

logger = get_logger()


class TelegramAdapter:
    """Telegram transport adapter with scheduled task support."""

    def __init__(self, message_handler: Any):
        self.config = Config()
        self.message_handler = message_handler
        self._application: Optional[Application] = None
        self._initialized = False
        self.scheduler = message_handler.core_bot.scheduler
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

    def _get_commands(self) -> TelegramCommands:
        """Resolve Telegram command handlers from the message handler."""
        return self.message_handler._commands

    async def _cmd_start(self, update: Any, context: Any) -> None:
        """Delegate /start command handling to the command adapter."""
        await self._get_commands().handle_start(update, context)

    async def _cmd_help(self, update: Any, context: Any) -> None:
        """Delegate /help command handling to the command adapter."""
        await self._get_commands().handle_help(update, context)

    def run(self) -> None:
        """Start the adapter runtime."""
        if not self._application:
            raise RuntimeError(
                "Application not created. Call create_application() first."
            )

        logger.info("Starting Telegram adapter with scheduler...")
        self._application.run_polling(allowed_updates=Any)
        logger.info("Adapter stopped")

    def stop(self) -> None:
        """Stop the Telegram application."""
        if self._application and self._application.running:
            logger.info("Stopping Telegram adapter...")
            self._application.stop()


def register_signal_handlers(
    adapter: Any,
    signal_fn: Callable[[int, Callable[..., Optional[None]]], Any] = signal.signal,
) -> None:
    """Register SIGINT/SIGTERM handlers that stop the adapter gracefully."""

    def _stop_adapter(_sig: int, _frame: Any) -> None:
        if hasattr(adapter, "stop"):
            adapter.stop()

    signal_fn(signal.SIGINT, _stop_adapter)
    signal_fn(signal.SIGTERM, _stop_adapter)


class TelegramApplicationSetup:
    """Create Telegram applications, register handlers, and wire lifecycle hooks."""

    def __init__(self, telegram_adapter: Any):
        self.telegram_adapter = telegram_adapter

    def create_application(
        self,
        application_builder_factory: Callable[[], Any],
        command_handler_cls: type[CommandHandler],
        message_handler_cls: type[MessageHandler],
        filters_module: Any,
    ) -> Application:
        """Build and configure the Telegram application."""
        builder = application_builder_factory().token(
            self.telegram_adapter.config.TELEGRAM_BOT_TOKEN
        )
        builder = builder.concurrent_updates(True)
        application = builder.build()
        self.telegram_adapter.message_handler.set_telegram_bot(application.bot)

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
        commands = self.telegram_adapter._get_commands()
        return [
            command_handler_cls("start", commands.handle_start),
            command_handler_cls("help", commands.handle_help),
            command_handler_cls("new", commands.handle_new_session),
            command_handler_cls("reset", commands.handle_reset_session),
            command_handler_cls(
                "approve", self.telegram_adapter.message_handler.handle_approve
            ),
            message_handler_cls(
                filters_module.TEXT & ~filters_module.COMMAND,
                self.telegram_adapter.message_handler.handle_message,
            ),
            message_handler_cls(
                filters_module.Document.ALL
                | filters_module.PHOTO
                | filters_module.VIDEO
                | filters_module.AUDIO
                | filters_module.VOICE,
                self.telegram_adapter.message_handler.handle_file,
            ),
        ]

    def _build_post_init_hook(self) -> Callable[[Application], Any]:
        """Build the post_init hook for command registration and scheduler startup."""

        async def post_init(application: Application) -> None:
            if self.telegram_adapter._initialized:
                logger.warning("Adapter already initialized, skipping post_init")
                return

            commands = TelegramCommands.build_menu_commands()
            await application.bot.set_my_commands(commands)
            logger.info("Bot commands registered in Telegram menu")

            self.telegram_adapter.scheduler._task = asyncio.create_task(
                self.telegram_adapter.scheduler.run_forever()
            )
            logger.info("Scheduler started as background task")
            self.telegram_adapter._initialized = True

        return post_init

    def _build_post_shutdown_hook(self) -> Callable[[Application], Any]:
        """Build the post_shutdown hook for graceful scheduler shutdown."""

        async def post_shutdown(_application: Application) -> None:
            self.telegram_adapter.scheduler.stop()
            if (
                self.telegram_adapter.scheduler._task
                and not self.telegram_adapter.scheduler._task.done()
            ):
                try:
                    await asyncio.wait_for(
                        self.telegram_adapter.scheduler._task, timeout=2.0
                    )
                except asyncio.TimeoutError:
                    logger.warning("Scheduler did not stop in time")
                except asyncio.CancelledError:
                    pass
            logger.info("Scheduler stopped")

        return post_shutdown
