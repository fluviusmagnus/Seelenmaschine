from typing import Any

from adapter.telegram.delivery import send_segmented_text, typing_indicator
from utils.logger import get_logger

logger = get_logger()


class ScheduledMessageSender:
    """Process scheduled task callbacks and deliver them through Telegram."""

    def __init__(self, config: Any, message_handler: Any):
        self.config = config
        self.message_handler = message_handler

    async def send_scheduled_message(
        self,
        application: Any,
        message: str,
        task_name: str = "Scheduled Task",
    ) -> None:
        """Process a scheduled task through the LLM and send the result."""
        if not application:
            logger.error("Cannot send scheduled message: application not initialized")
            return

        try:
            async with typing_indicator(
                lambda: application.bot.send_chat_action(
                    chat_id=self.config.TELEGRAM_USER_ID,
                    action="typing",
                ),
                "Scheduled typing indicator failed",
            ):
                logger.info(
                    f"Processing scheduled task '{task_name}': {message[:50]}..."
                )
                llm_response = await self.message_handler._handle_scheduled_message(
                    message, task_name
                )

                formatted_response = (
                    self.message_handler._format_response_for_telegram(llm_response)
                )
                segments = self.message_handler._split_message_into_segments(
                    formatted_response
                )
                logger.debug(f"Scheduled response split into {len(segments)} segments")

                await send_segmented_text(
                    segments=segments,
                    send_html=lambda segment: application.bot.send_message(
                        chat_id=self.config.TELEGRAM_USER_ID,
                        text=segment,
                        parse_mode="HTML",
                    ),
                    send_plain=lambda segment: application.bot.send_message(
                        chat_id=self.config.TELEGRAM_USER_ID,
                        text=segment,
                    ),
                    html_warning_template=(
                        "HTML parsing failed for scheduled segment {index}, "
                        "sending plain text: {error}"
                    ),
                    fatal_error_template=(
                        "Failed to send scheduled segment {index}: {error}"
                    ),
                    preview_text=lambda text, _max_length=120: text,
                    debug_prefix="Sent scheduled segment",
                )

                logger.info(
                    f"Scheduled task response sent ({len(segments)} segments): {llm_response[:50]}..."
                )
        except Exception as error:
            logger.error(
                f"Failed to process/send scheduled message: {error}",
                exc_info=True,
            )
            raise
