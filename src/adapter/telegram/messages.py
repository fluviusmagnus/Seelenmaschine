from typing import Any

from adapter.telegram.delivery import send_segmented_text, typing_indicator
from telegram import Update
from telegram.ext import ContextTypes

from adapter.telegram.files import TelegramFiles
from core.approval import ApprovalService
from utils.logger import get_logger

logger = get_logger()


class TelegramMessages:
    """Handle Telegram messages, files, and scheduled callbacks."""

    def __init__(self, handler: Any):
        self.handler = handler

    def _resolve_handler_component(
        self,
        attr_name: str,
        expected_type: type[Any],
        factory: Any,
    ) -> Any:
        """Prefer a concrete handler-owned helper, otherwise build a local fallback."""
        component = getattr(self.handler, attr_name, None)
        if isinstance(component, expected_type):
            return component
        return factory()

    async def handle_scheduled_message(
        self, message: str, task_name: str = "Scheduled Task"
    ) -> str:
        """Handle a scheduled task callback through the conversation pipeline."""
        logger.info(f"Processing scheduled task '{task_name}': {message[:50]}...")
        return await self.process_scheduled_task(message, task_name)

    async def handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle regular text messages."""
        if not update.effective_user or not update.message or not update.message.text:
            return

        user_id = update.effective_user.id
        if user_id != self.handler.core_bot.config.TELEGRAM_USER_ID:
            await update.message.reply_text("Unauthorized access.")
            logger.warning(f"Unauthorized message from user {user_id}")
            return

        user_message = update.message.text
        logger.info(f"Received message: {user_message[:50]}...")

        approval_service = getattr(self.handler, "_approval_service", None)
        if isinstance(approval_service, ApprovalService):
            pending_request = approval_service.abort_pending()
        else:
            pending_request = self.handler._pending_approval
            if pending_request and not pending_request.future.done():
                pending_request.future.set_result(False)
                logger.info(
                    "Pending approval aborted by non-/approve user message: "
                    f"tool={pending_request.tool_name}, reason={pending_request.reason}"
                )

        if pending_request is not None:
            await update.message.reply_text("❌ Pending action aborted.")
            return

        try:
            async with typing_indicator(
                lambda: context.bot.send_chat_action(
                    chat_id=update.effective_chat.id, action="typing"
                ),
                "Typing indicator failed",
            ):
                response = await self.process_message(user_message)
                logger.info(
                    "Prepared final text for Telegram reply: "
                    f"{self.handler._preview_text(response)}"
                )
                formatted_response = self.handler._format_response_for_telegram(
                    response
                )
                segments = self.handler._split_message_into_segments(formatted_response)
                logger.info(
                    f"Sending {len(segments)} Telegram segment(s) for text message"
                )

                await send_segmented_text(
                    segments=segments,
                    send_html=lambda segment: update.message.reply_text(
                        segment, parse_mode="HTML"
                    ),
                    send_plain=update.message.reply_text,
                    html_warning_template=(
                        "HTML parsing failed for segment {index}, "
                        "sending as plain text: {error}"
                    ),
                    fatal_error_template="Failed to send segment {index}: {error}",
                )
        except Exception as error:
            logger.error(f"Error handling message: {error}", exc_info=True)
            await update.message.reply_text(
                "Sorry, an error occurred while processing your message.\n\n"
                f"Details: {self.handler._format_exception_for_user(error)}"
            )

    async def handle_file(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        files = self._resolve_handler_component(
            "_files",
            TelegramFiles,
            lambda: TelegramFiles(
                config=self.handler.core_bot.config,
                memory=self.handler.core_bot.memory,
            ),
        )
        await files.handle_file(
            update=update,
            context=context,
            process_message=self.process_message,
            format_response_for_telegram=self.handler._format_response_for_telegram,
            split_message_into_segments=self.handler._split_message_into_segments,
            preview_text=self.handler._preview_text,
            format_exception_for_user=self.handler._format_exception_for_user,
        )

    async def process_message(self, user_message: str) -> str:
        return await self.handler.core_bot.process_message(
            user_message,
            intermediate_callback=self.handler._send_intermediate_response,
        )

    async def process_scheduled_task(
        self, task_message: str, task_name: str = "Scheduled Task"
    ) -> str:
        return await self.handler.core_bot.process_scheduled_task(
            task_message,
            task_name,
            intermediate_callback=self.handler._send_intermediate_response,
        )
