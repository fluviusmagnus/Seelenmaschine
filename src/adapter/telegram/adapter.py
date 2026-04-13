import asyncio
import signal
from typing import Any, Callable, List, Optional

from telegram import Update
from telegram.error import NetworkError
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from adapter.telegram.commands import TelegramCommands
from core.config import Config
from utils.logger import get_logger

logger = get_logger()


def register_stop_signal_handlers(
    stop_callback: Callable[[], None],
    signal_fn: Callable[[int, Callable[..., Optional[None]]], Any] = signal.signal,
) -> None:
    """Register SIGINT/SIGTERM handlers that stop the Telegram runtime gracefully."""

    def _stop_runtime(_sig: int, _frame: Any) -> None:
        stop_callback()

    signal_fn(signal.SIGINT, _stop_runtime)
    signal_fn(signal.SIGTERM, _stop_runtime)


class TelegramAdapter:
    """Telegram transport adapter with scheduled task support."""

    def __init__(self, message_handler: Any):
        self.config = Config()
        self.message_handler = message_handler
        self._application: Optional[Application] = None
        self.scheduler = message_handler.core_bot.scheduler
        self._application_setup = TelegramApplicationSetup(self)
        self.scheduler.set_message_callback(self._send_scheduled_message)

    async def _send_scheduled_message(
        self,
        message: str,
        task_name: str = "Scheduled Task",
        task_id: str | None = None,
    ) -> None:
        """Send a scheduled message through the Telegram controller."""
        await self.message_handler.send_scheduled_message(
            application=self._application,
            message=message,
            task_name=task_name,
            task_id=task_id,
        )

    def create_application(
        self,
    ) -> None:
        """Create and configure the Telegram application."""
        self._application = self._application_setup.create_application(
            application_builder_factory=Application.builder,
            command_handler_cls=CommandHandler,
            message_handler_cls=MessageHandler,
            filters_module=filters,
        )

    def run(self) -> None:
        """Start the adapter runtime."""
        if not self._application:
            raise RuntimeError(
                "Application not created. Call create_application() first."
            )

        logger.info("Starting Telegram adapter with scheduler...")
        self._ensure_event_loop()
        try:
            self._application.run_polling(
                allowed_updates=Update.ALL_TYPES,
                bootstrap_retries=self.config.TELEGRAM_BOOTSTRAP_RETRIES,
            )
        except NetworkError as exc:
            logger.error(
                "Failed to connect to Telegram API. Please verify DNS/network access "
                "from the host environment and confirm the bot token is valid. "
                f"Original error: {exc}"
            )
            raise RuntimeError(
                "Telegram startup failed because the Telegram API could not be reached. "
                "This is usually a DNS or outbound network issue in the runtime environment."
            ) from exc
        logger.info("Adapter stopped")

    def stop(self) -> None:
        """Stop the Telegram application."""
        if self._application and self._application.running:
            logger.info("Stopping Telegram adapter...")
            self._application.stop()

    @staticmethod
    def _ensure_event_loop() -> asyncio.AbstractEventLoop:
        """Ensure a current event loop exists for sync Telegram startup paths."""
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            pass

        try:
            loop = asyncio.get_event_loop_policy().get_event_loop()
            if loop.is_closed():
                raise RuntimeError
            return loop
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop


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
        builder = builder.get_updates_connect_timeout(
            self.telegram_adapter.config.TELEGRAM_GET_UPDATES_CONNECT_TIMEOUT
        )
        builder = builder.get_updates_read_timeout(
            self.telegram_adapter.config.TELEGRAM_GET_UPDATES_READ_TIMEOUT
        )
        builder = builder.get_updates_write_timeout(
            self.telegram_adapter.config.TELEGRAM_GET_UPDATES_WRITE_TIMEOUT
        )
        builder = builder.get_updates_pool_timeout(
            self.telegram_adapter.config.TELEGRAM_GET_UPDATES_POOL_TIMEOUT
        )
        builder = builder.connect_timeout(self.telegram_adapter.config.TELEGRAM_CONNECT_TIMEOUT)
        builder = builder.read_timeout(self.telegram_adapter.config.TELEGRAM_READ_TIMEOUT)
        builder = builder.write_timeout(self.telegram_adapter.config.TELEGRAM_WRITE_TIMEOUT)
        builder = builder.pool_timeout(self.telegram_adapter.config.TELEGRAM_POOL_TIMEOUT)
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
        commands = self.telegram_adapter.message_handler.commands
        return [
            command_handler_cls("start", commands.handle_start),
            command_handler_cls("help", commands.handle_help),
            command_handler_cls("new", commands.handle_new_session),
            command_handler_cls("reset", commands.handle_reset_session),
            command_handler_cls("approve", commands.handle_approve),
            command_handler_cls("stop", commands.handle_stop),
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

    def _build_post_init_hook(
        self,
    ) -> Callable[[Application], Any]:
        """Build the Telegram post_init hook."""

        async def post_init(application: Application) -> None:
            commands = TelegramCommands.build_menu_commands()
            await application.bot.set_my_commands(commands)
            logger.info("Bot commands registered in Telegram menu")
            await self.telegram_adapter.message_handler.core_bot.warmup_tool_runtime()
            self.telegram_adapter.scheduler.start()

        return post_init

    def _build_post_shutdown_hook(self) -> Callable[[Application], Any]:
        """Build the Telegram post_shutdown hook."""

        async def post_shutdown(_application: Application) -> None:
            self.telegram_adapter.scheduler.stop()
            await self.telegram_adapter.scheduler.wait_stopped()
            logger.info("Scheduler stopped")

        return post_shutdown
