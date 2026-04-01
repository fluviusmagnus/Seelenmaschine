"""Telegram controller boundary."""

from typing import Any, Optional

from adapter.telegram.commands import TelegramCommands
from adapter.telegram.delivery import TelegramAccessGuard, TelegramResponseSender
from adapter.telegram.files import TelegramFiles
from adapter.telegram.formatter import TelegramResponseFormatter
from adapter.telegram.messages import TelegramMessages
from core.bot import CoreBot
from core.file_delivery_service import FileDeliveryService
from utils.logger import get_logger

logger = get_logger()


class TelegramController:
    """Telegram-facing controller that wires explicit services and delegates work."""

    @staticmethod
    def _preview_text(text: Optional[str], max_length: int = 120) -> str:
        """Build a compact single-line preview for logs."""
        if text is None:
            return ""

        normalized = " ".join(str(text).split())
        if len(normalized) <= max_length:
            return normalized
        return f"{normalized[:max_length]}..."

    @staticmethod
    def _format_exception_for_user(error: Exception) -> str:
        """Build a concise user-facing error summary."""
        message = str(error).strip() or type(error).__name__
        if len(message) > 300:
            message = f"{message[:297]}..."
        return message

    def __init__(self, core_bot: Optional[CoreBot] = None):
        """Initialize Telegram-facing services around the core bot."""
        self.core_bot = core_bot or CoreBot()
        self.telegram_bot = None

        access_guard = TelegramAccessGuard(self.core_bot.config)
        response_sender = TelegramResponseSender(
            config=self.core_bot.config,
            formatter=TelegramResponseFormatter(),
        )
        file_service = TelegramFiles(config=self.core_bot.config)
        self.core_bot.file_delivery_service = FileDeliveryService(
            config=self.core_bot.config,
            memory=self.core_bot.memory,
            telegram_files=file_service,
        )
        approval_service = self.core_bot.approval_service

        self.response_sender = response_sender
        self.commands = TelegramCommands(
            core_bot=self.core_bot,
            access_guard=access_guard,
            approval_service=approval_service,
            get_telegram_bot=lambda: self.telegram_bot,
            preview_text=self._preview_text,
            format_exception_for_user=self._format_exception_for_user,
        )

        self.messages = TelegramMessages(
            core_bot=self.core_bot,
            access_guard=access_guard,
            approval_service=approval_service,
            files=file_service,
            response_sender=response_sender,
            preview_text=self._preview_text,
            format_exception_for_user=self._format_exception_for_user,
            intermediate_callback=self._send_intermediate_response,
        )

        self.core_bot.initialize_telegram_runtime(
            self,
            approval_delegate=self.commands,
            preview_text=self._preview_text,
        )
        logger.info("TelegramController initialized")

    def set_telegram_bot(self, bot: Any) -> None:
        """Inject Telegram bot instance for proactive notifications and file sending."""
        self.telegram_bot = bot
        self.core_bot.get_tool_executor_service().telegram_bot = bot
        logger.info("Telegram bot instance injected into TelegramController")

    async def _send_intermediate_response(self, text: str) -> None:
        """Stream intermediate assistant text to Telegram when available."""
        if not text.strip() or not self.telegram_bot:
            return
        try:
            await self.response_sender.send_bot_text(
                telegram_bot=self.telegram_bot,
                chat_id=self.core_bot.config.TELEGRAM_USER_ID,
                text=text,
                html_warning_template=(
                    "HTML parsing failed for intermediate segment {index}, "
                    "sending as plain text: {error}"
                ),
                fatal_error_template=(
                    "Failed to send intermediate segment {index}: {error}"
                ),
            )
        except Exception as error:
            logger.error(f"Failed to send intermediate response: {error}")

    async def handle_message(self, update: Any, context: Any) -> None:
        """Handle regular text messages."""
        await self.messages.handle_message(update, context)

    async def handle_file(self, update: Any, context: Any) -> None:
        """Handle incoming Telegram attachments by saving them and notifying the LLM."""
        await self.messages.handle_file(update, context)

    async def process_scheduled_task(
        self,
        task_message: str,
        task_name: str = "Scheduled Task",
        task_id: Optional[str] = None,
    ) -> str:
        """Process a scheduled task message through the LLM."""
        return await self.messages.process_scheduled_task(
            task_message,
            task_name,
            task_id,
        )