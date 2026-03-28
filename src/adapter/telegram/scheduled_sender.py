import asyncio
import random
from typing import Any

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

        async def _keep_typing_indicator() -> None:
            while True:
                try:
                    await application.bot.send_chat_action(
                        chat_id=self.config.TELEGRAM_USER_ID,
                        action="typing",
                    )
                    await asyncio.sleep(3)
                except Exception as error:
                    logger.warning(f"Scheduled typing indicator failed: {error}")
                    await asyncio.sleep(3)

        try:
            typing_task = asyncio.create_task(_keep_typing_indicator())
            try:
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

                for index, segment in enumerate(segments):
                    try:
                        await application.bot.send_message(
                            chat_id=self.config.TELEGRAM_USER_ID,
                            text=segment,
                            parse_mode="HTML",
                        )
                        logger.debug(
                            f"Sent scheduled segment {index + 1}/{len(segments)} ({len(segment)} chars)"
                        )

                        if index < len(segments) - 1:
                            delay = random.uniform(1.0, 2.0)
                            logger.debug(f"Waiting {delay:.1f}s before next segment")
                            await asyncio.sleep(delay)
                    except Exception as error:
                        logger.warning(
                            "HTML parsing failed for scheduled segment "
                            f"{index + 1}, sending plain text: {error}"
                        )
                        try:
                            await application.bot.send_message(
                                chat_id=self.config.TELEGRAM_USER_ID,
                                text=segment,
                            )
                        except Exception as fallback_error:
                            logger.error(
                                f"Failed to send scheduled segment {index + 1}: {fallback_error}"
                            )

                logger.info(
                    f"Scheduled task response sent ({len(segments)} segments): {llm_response[:50]}..."
                )
            finally:
                typing_task.cancel()
                try:
                    await typing_task
                except asyncio.CancelledError:
                    pass
        except Exception as error:
            logger.error(
                f"Failed to process/send scheduled message: {error}",
                exc_info=True,
            )
            raise
