"""Telegram controller composition root and handler boundary."""

from pathlib import Path
from typing import Any, Optional

from adapter.telegram.commands import TelegramCommands
from adapter.telegram.delivery import (
    TelegramAccessGuard,
    TelegramResponseSender,
    typing_indicator,
)
from adapter.telegram.files import TelegramFiles
from adapter.telegram.formatter import TelegramResponseFormatter
from core.adapter_contracts import AdapterRuntimeCapabilities
from core.bot import CoreBot
from core.file_service import FileDeliveryService
from core.hitl import ApprovalService, ToolLoopAbortedError
from utils.logger import get_logger

logger = get_logger()


class TelegramController:
    """Telegram-facing boundary that owns request handling and composition."""

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
        def _clean_message(value: Any) -> str:
            return str(value).strip().strip("\"'")

        def _build_summary(exc: BaseException) -> str:
            error_type = type(exc).__name__

            if isinstance(exc, KeyError):
                missing_key = _clean_message(exc)
                if missing_key:
                    return f"Missing expected field: {missing_key}"
                return "Missing expected field in internal response data"

            if isinstance(exc, FileNotFoundError):
                file_path = getattr(exc, "filename", None)
                if file_path:
                    return f"File not found: {file_path}"
                return "File not found"

            if isinstance(exc, PermissionError):
                file_path = getattr(exc, "filename", None)
                if file_path:
                    return f"Permission denied while accessing: {file_path}"
                return "Permission denied"

            if isinstance(exc, TimeoutError):
                message = _clean_message(exc)
                return f"TimeoutError: {message}" if message else "TimeoutError: operation timed out"

            message = _clean_message(exc)
            if message:
                if message == error_type:
                    return error_type
                return f"{error_type}: {message}"

            return f"{error_type}: no additional details available"

        chain: list[BaseException] = []
        seen: set[int] = set()
        current: BaseException | None = error

        while current is not None and id(current) not in seen:
            chain.append(current)
            seen.add(id(current))
            current = current.__cause__ or current.__context__

        message = _build_summary(chain[0])
        for chained_error in chain[1:]:
            candidate = _build_summary(chained_error)
            if candidate and candidate != message:
                message = f"{message} (caused by: {candidate})"
                break

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
        )
        approval_service = self.core_bot.approval_service

        self.response_sender = response_sender
        self.access_guard = access_guard
        self.approval_service = approval_service
        self.files = file_service
        self.commands = TelegramCommands(
            core_bot=self.core_bot,
            access_guard=access_guard,
            approval_service=approval_service,
            get_telegram_bot=lambda: self.telegram_bot,
            preview_text=self._preview_text,
            format_exception_for_user=self._format_exception_for_user,
        )

        async def _send_status_message(text: str) -> None:
            if self.telegram_bot is None:
                return
            await self.telegram_bot.send_message(
                chat_id=self.core_bot.config.TELEGRAM_USER_ID,
                text=text,
                parse_mode="HTML",
            )

        capabilities = AdapterRuntimeCapabilities(
            preview_text=self._preview_text,
            send_file_to_user=lambda **kwargs: self._send_file_to_user_via_telegram(
                files=file_service,
                **kwargs,
            ),
            send_status_message=_send_status_message,
        )

        self.core_bot.initialize_adapter_runtime(
            approval_delegate=self.commands,
            capabilities=capabilities,
        )
        logger.info("TelegramController initialized")

    async def _send_file_to_user_via_telegram(
        self,
        *,
        files: TelegramFiles,
        file_path: str,
        caption: Optional[str] = None,
        file_type: str = "auto",
    ) -> dict[str, Any]:
        """Send a local file using Telegram transport after core policy validation."""
        prepared = self.core_bot.file_delivery_service.prepare_file_delivery(
            file_path=file_path,
            caption=caption,
            file_type=file_type,
        )
        resolved_path = Path(prepared["resolved_path"])
        delivery_method = await files.send_local_file(
            telegram_bot=self.telegram_bot,
            resolved_path=resolved_path,
            caption=caption,
            file_type=file_type,
        )
        event_text = self.core_bot.file_delivery_service.build_sent_file_event_message(
            resolved_path,
            delivery_method,
            caption,
            platform_label="telegram",
        )
        return {
            "status": "sent",
            "delivery_method": delivery_method,
            "resolved_path": str(resolved_path.resolve()),
            "caption": caption,
            "event_message": event_text,
        }

    def set_telegram_bot(self, bot: Any) -> None:
        """Inject Telegram bot instance for proactive notifications and file sending."""
        self.telegram_bot = bot
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

    async def _safe_reply_text(self, reply_text: Any, text: str) -> None:
        """Best-effort Telegram reply that never re-raises delivery failures."""
        try:
            await reply_text(text)
        except Exception as send_error:
            logger.error(
                f"Failed to send Telegram reply message: {send_error}",
                exc_info=True,
            )

    def _format_user_error_text(
        self,
        *,
        scenario: str,
        error: Exception,
        subject_label: str | None = None,
        subject: str | None = None,
    ) -> str:
        """Build a consistent user-facing Telegram error message."""
        scenario_titles = {
            "message": "Sorry, an error occurred while processing your message.",
            "file": "Sorry, an error occurred while processing your file.",
            "scheduled_task": (
                "Sorry, an error occurred while processing a scheduled task."
            ),
        }
        title = scenario_titles.get(
            scenario,
            "Sorry, an error occurred while processing your request.",
        )

        details = self._format_exception_for_user(error)
        lines = [title, ""]
        normalized_subject = subject.strip() if isinstance(subject, str) else ""
        normalized_label = subject_label.strip() if isinstance(subject_label, str) else ""
        if normalized_subject and normalized_label:
            lines.append(f"{normalized_label}: {normalized_subject}")
        lines.append(f"Details: {details}")
        return "\n".join(lines)

    async def send_scheduled_message(
        self,
        application: Any,
        message: str,
        task_name: str = "Scheduled Task",
        task_id: str | None = None,
    ) -> None:
        """Process a scheduled task and send the result through the bot."""
        if not application:
            logger.error("Cannot send scheduled message: application not initialized")
            return

        try:
            async with self.core_bot.get_processing_lock():
                async with typing_indicator(
                    lambda: application.bot.send_chat_action(
                        chat_id=self.core_bot.config.TELEGRAM_USER_ID,
                        action="typing",
                    ),
                    "Scheduled typing indicator failed",
                ):
                    logger.info(
                        f"Processing scheduled task '{task_name}': {message[:50]}..."
                    )
                    try:
                        response = await self.process_scheduled_task(
                            message, task_name, task_id
                        )
                    except Exception as error:
                        logger.error(
                            f"Error while processing scheduled task '{task_name}': {error}",
                            exc_info=True,
                        )
                        task_label = task_name.strip() if isinstance(task_name, str) else ""
                        if not task_label or task_label == "Scheduled Task":
                            task_label = message.strip() if isinstance(message, str) else ""
                        response = self._format_user_error_text(
                            scenario="scheduled_task",
                            error=error,
                            subject_label="Task",
                            subject=task_label,
                        )
                    await self.response_sender.send_bot_text(
                        telegram_bot=application.bot,
                        chat_id=self.core_bot.config.TELEGRAM_USER_ID,
                        text=response,
                        html_warning_template=(
                            "HTML parsing failed for scheduled segment {index}, "
                            "sending plain text: {error}"
                        ),
                        fatal_error_template=(
                            "Failed to send scheduled segment {index}: {error}"
                        ),
                        preview_text=self._preview_text,
                        debug_prefix="Sent scheduled segment",
                    )
                await self.core_bot.run_post_response_summary_check(
                    context_label="scheduled task response delivery"
                )
                logger.debug(
                    "Scheduled task response sent: "
                    f"{self._preview_text(response)}"
                )
        except Exception as error:
            logger.error(
                f"Failed to process/send scheduled message: {error}",
                exc_info=True,
            )
            raise

    async def process_message(
        self,
        user_message: str,
        *,
        message_for_embedding: str | None = None,
    ) -> str:
        """Process a message through the core conversation pipeline."""
        return await self.core_bot.process_message(
            user_message,
            message_for_embedding=message_for_embedding,
            intermediate_callback=self._send_intermediate_response,
        )

    async def process_scheduled_task(
        self,
        task_message: str,
        task_name: str = "Scheduled Task",
        task_id: str | None = None,
    ) -> str:
        """Process a scheduled task through the core conversation pipeline."""
        return await self.core_bot.process_scheduled_task(
            task_message,
            task_name,
            task_id,
            intermediate_callback=self._send_intermediate_response,
        )

    async def handle_message(self, update: Any, context: Any) -> None:
        """Handle regular text messages."""
        if not update.effective_user or not update.message or not update.message.text:
            return

        if await self.access_guard.reject_unauthorized(
            update,
            log_message="Unauthorized message",
        ):
            return

        user_message = update.message.text
        logger.debug(f"Received message: {user_message[:50]}...")

        approval_service = self.approval_service
        if isinstance(approval_service, ApprovalService):
            pending_request = approval_service.abort_pending(user_message=user_message)
        else:
            pending_request = None

        if pending_request is not None:
            return

        try:
            async with typing_indicator(
                lambda: context.bot.send_chat_action(
                    chat_id=update.effective_chat.id, action="typing"
                ),
                "Typing indicator failed",
            ):
                async with self.core_bot.get_processing_lock():
                    response = await self.process_message(user_message)
                    await self.response_sender.send_reply_text(
                        reply_text=update.message.reply_text,
                        text=response,
                        html_warning_template=(
                            "HTML parsing failed for segment {index}, "
                            "sending as plain text: {error}"
                        ),
                        fatal_error_template="Failed to send segment {index}: {error}",
                        preview_text=self._preview_text,
                        debug_prefix="Sending Telegram text segment",
                    )
                await self.core_bot.run_post_response_summary_check(
                    context_label="message reply delivery"
                )
        except ToolLoopAbortedError as error:
            logger.info(f"Tool loop aborted by user request: {error}")
            await self._safe_reply_text(
                update.message.reply_text,
                "🛑 Current tool loop stopped.",
            )
        except Exception as error:
            logger.error(f"Error handling message: {error}", exc_info=True)
            await self._safe_reply_text(
                update.message.reply_text,
                self._format_user_error_text(
                    scenario="message",
                    error=error,
                ),
            )

    async def handle_file(self, update: Any, context: Any) -> None:
        """Handle incoming Telegram attachments by saving them and notifying the LLM."""
        await self.files.handle_file(
            update=update,
            context=context,
            process_message=self.process_message,
            response_sender=self.response_sender,
            preview_text=self._preview_text,
            format_exception_for_user=self._format_exception_for_user,
            format_user_error_text=self._format_user_error_text,
        )
