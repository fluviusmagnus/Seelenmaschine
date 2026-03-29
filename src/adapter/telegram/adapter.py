import asyncio
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
        self, message: str, task_name: str = "Scheduled Task"
    ) -> None:
        """Send a scheduled message to the user via the LLM flow."""
        await self.message_handler.messages.send_scheduled_message(
            application=self._application,
            message=message,
            task_name=task_name,
        )

    def create_application(
        self,
        *,
        post_init: Optional[Callable[[Application], Any]] = None,
        post_shutdown: Optional[Callable[[Application], Any]] = None,
    ) -> None:
        """Create and configure the Telegram application."""
        self._application = self._application_setup.create_application(
            application_builder_factory=Application.builder,
            command_handler_cls=CommandHandler,
            message_handler_cls=MessageHandler,
            filters_module=filters,
            post_init=post_init,
            post_shutdown=post_shutdown,
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
        post_init: Optional[Callable[[Application], Any]] = None,
        post_shutdown: Optional[Callable[[Application], Any]] = None,
    ) -> Application:
        """Build and configure the Telegram application."""
        builder = application_builder_factory().token(
            self.telegram_adapter.config.TELEGRAM_BOT_TOKEN
        )
        builder = builder.concurrent_updates(True)
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

        application.post_init = self._build_post_init_hook(post_init)
        if post_shutdown is not None:
            application.post_shutdown = post_shutdown

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
        external_post_init: Optional[Callable[[Application], Any]],
    ) -> Callable[[Application], Any]:
        """Build the post_init hook for Telegram command registration."""

        async def post_init(application: Application) -> None:
            commands = TelegramCommands.build_menu_commands()
            await application.bot.set_my_commands(commands)
            logger.info("Bot commands registered in Telegram menu")

            if external_post_init is not None:
                await external_post_init(application)

        return post_init
