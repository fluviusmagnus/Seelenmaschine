import asyncio
import mimetypes
import random
import re
from pathlib import Path
from typing import Any, Dict, Optional

from telegram import Update
from telegram.ext import ContextTypes

from adapter.telegram.files import TelegramFiles
from core.approval import ApprovalService
from core.conversation import ConversationService
from utils.logger import get_logger

logger = get_logger()


class TelegramMessages:
    """Handle Telegram messages, files, and scheduled callbacks."""

    def __init__(self, handler: Any):
        self.handler = handler

    def _resolve_message_processor(self) -> Any:
        """Prefer an explicitly patched handler processor when available."""
        processor = getattr(self.handler, "_process_message", None)
        if (
            callable(processor)
            and not (
                getattr(processor, "__self__", None) is self.handler
                and getattr(processor, "__name__", "") == "_process_message"
            )
        ):
            return processor
        return self.process_message

    def _resolve_scheduled_processor(self) -> Any:
        """Prefer an explicitly patched scheduled-task processor when available."""
        processor = getattr(self.handler, "_process_scheduled_task", None)
        if (
            callable(processor)
            and not (
                getattr(processor, "__self__", None) is self.handler
                and getattr(processor, "__name__", "") == "_process_scheduled_task"
            )
        ):
            return processor
        return self.process_scheduled_task

    def _resolve_files(self) -> TelegramFiles:
        """Prefer the handler's concrete Telegram files helper when available."""
        files = getattr(self.handler, "_files", None)
        if isinstance(files, TelegramFiles):
            return files
        return TelegramFiles(
            config=getattr(self.handler, "config", None),
            memory=getattr(self.handler, "memory", None),
        )

    async def handle_scheduled_message(
        self, message: str, task_name: str = "Scheduled Task"
    ) -> str:
        """Handle a scheduled task callback through the conversation pipeline."""
        logger.info(f"Processing scheduled task '{task_name}': {message[:50]}...")
        return await self._resolve_scheduled_processor()(message, task_name)

    async def handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle regular text messages."""
        if not update.effective_user or not update.message or not update.message.text:
            return

        user_id = update.effective_user.id
        if user_id != self.handler.config.TELEGRAM_USER_ID:
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

        async def _keep_typing_indicator() -> None:
            while True:
                try:
                    await context.bot.send_chat_action(
                        chat_id=update.effective_chat.id, action="typing"
                    )
                    await asyncio.sleep(3)
                except Exception as error:
                    logger.warning(f"Typing indicator failed: {error}")
                    await asyncio.sleep(3)

        try:
            typing_task = asyncio.create_task(_keep_typing_indicator())
            try:
                response = await self._resolve_message_processor()(user_message)
                logger.info(
                    "Prepared final text for Telegram reply: "
                    f"{self.handler._preview_text(response)}"
                )
                formatted_response = self.handler._format_response_for_telegram(response)
                segments = self.handler._split_message_into_segments(formatted_response)
                logger.info(
                    f"Sending {len(segments)} Telegram segment(s) for text message"
                )

                for index, segment in enumerate(segments):
                    try:
                        await update.message.reply_text(segment, parse_mode="HTML")
                        if index < len(segments) - 1:
                            await asyncio.sleep(random.uniform(1.0, 2.0))
                    except Exception as error:
                        logger.warning(
                            "HTML parsing failed for segment "
                            f"{index + 1}, sending as plain text: {error}"
                        )
                        try:
                            await update.message.reply_text(segment)
                        except Exception as fallback_error:
                            logger.error(
                                f"Failed to send segment {index + 1}: {fallback_error}"
                            )
            finally:
                typing_task.cancel()
                try:
                    await typing_task
                except asyncio.CancelledError:
                    pass
        except Exception as error:
            logger.error(f"Error handling message: {error}", exc_info=True)
            await update.message.reply_text(
                "Sorry, an error occurred while processing your message.\n\n"
                f"Details: {self.handler._format_exception_for_user(error)}"
            )

    def sanitize_filename(self, filename: str) -> str:
        sanitized = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", filename).strip(" .")
        return sanitized or "file"

    def guess_extension(
        self, original_name: Optional[str], mime_type: Optional[str], file_type: str
    ) -> str:
        if original_name:
            suffix = Path(original_name).suffix
            if suffix:
                return suffix
        if mime_type:
            guessed = mimetypes.guess_extension(mime_type)
            if guessed:
                return guessed
        fallback_extensions = {
            "photo": ".jpg",
            "video": ".mp4",
            "audio": ".mp3",
            "voice": ".ogg",
            "document": "",
        }
        return fallback_extensions.get(file_type, "")

    def build_media_file_path(
        self,
        original_name: Optional[str],
        file_unique_id: str,
        mime_type: Optional[str],
        file_type: str,
    ) -> Path:
        base_name = self.sanitize_filename(original_name or file_type)
        base_stem = Path(base_name).stem or file_type
        extension = self.guess_extension(original_name, mime_type, file_type)
        timestamp = asyncio.get_running_loop().time()
        unique_part = f"{int(timestamp * 1000)}_{file_unique_id}"
        filename = f"{base_stem}_{unique_part}{extension}"
        return self.handler.config.MEDIA_DIR / filename

    def extract_file_info_from_update(
        self, update: Update
    ) -> Optional[Dict[str, Any]]:
        if not update.message:
            return None
        message = update.message
        caption = getattr(message, "caption", None)

        if message.document:
            doc = message.document
            return {
                "file_id": doc.file_id,
                "file_unique_id": doc.file_unique_id,
                "file_type": "document",
                "original_name": doc.file_name,
                "mime_type": doc.mime_type,
                "file_size": doc.file_size,
                "caption": caption,
            }
        if message.photo:
            photo = message.photo[-1]
            return {
                "file_id": photo.file_id,
                "file_unique_id": photo.file_unique_id,
                "file_type": "photo",
                "original_name": None,
                "mime_type": "image/jpeg",
                "file_size": photo.file_size,
                "caption": caption,
            }
        if message.video:
            video = message.video
            return {
                "file_id": video.file_id,
                "file_unique_id": video.file_unique_id,
                "file_type": "video",
                "original_name": video.file_name,
                "mime_type": video.mime_type,
                "file_size": video.file_size,
                "caption": caption,
            }
        if message.audio:
            audio = message.audio
            return {
                "file_id": audio.file_id,
                "file_unique_id": audio.file_unique_id,
                "file_type": "audio",
                "original_name": audio.file_name,
                "mime_type": audio.mime_type,
                "file_size": audio.file_size,
                "caption": caption,
            }
        if message.voice:
            voice = message.voice
            return {
                "file_id": voice.file_id,
                "file_unique_id": voice.file_unique_id,
                "file_type": "voice",
                "original_name": None,
                "mime_type": voice.mime_type,
                "file_size": voice.file_size,
                "caption": caption,
            }
        return None

    async def download_telegram_file(
        self, context: ContextTypes.DEFAULT_TYPE, file_id: str, destination: Path
    ) -> Path:
        telegram_file = await context.bot.get_file(file_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        await telegram_file.download_to_drive(custom_path=str(destination))
        return destination

    def build_file_event_message(
        self, file_info: Dict[str, Any], saved_path: Path
    ) -> str:
        original_name = file_info.get("original_name") or saved_path.name
        message_lines = [
            "[System Event] The user has sent a file.",
            f"File type: {file_info['file_type']}",
            f"Original filename: {original_name}",
            f"Saved to: {self.handler._format_saved_media_path(saved_path)}",
        ]
        mime_type = file_info.get("mime_type")
        if mime_type:
            message_lines.append(f"MIME type: {mime_type}")
        file_size = file_info.get("file_size")
        if file_size is not None:
            message_lines.append(f"File size: {file_size} bytes")
        caption = file_info.get("caption")
        if caption:
            message_lines.append(f"Caption: {caption}")
        return "\n".join(message_lines)

    async def handle_file(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        await self._resolve_files().handle_file(
            update=update,
            context=context,
            extract_file_info=self.extract_file_info_from_update,
            build_media_file_path=self.build_media_file_path,
            download_telegram_file=self.download_telegram_file,
            build_file_event_message=self.build_file_event_message,
            process_message=self._resolve_message_processor(),
            format_response_for_telegram=self.handler._format_response_for_telegram,
            split_message_into_segments=self.handler._split_message_into_segments,
            preview_text=self.handler._preview_text,
            format_exception_for_user=self.handler._format_exception_for_user,
        )

    async def process_message(self, user_message: str) -> str:
        service = getattr(self.handler, "_conversation_service", None)
        if not isinstance(service, ConversationService):
            service = ConversationService(
                config=getattr(self.handler, "config", None),
                memory=self.handler.memory,
                embedding_client=getattr(self.handler, "embedding_client", None),
                llm_client=self.handler.llm_client,
                memory_search_tool=self.handler.memory_search_tool,
                mcp_client=getattr(self.handler, "mcp_client", None),
                ensure_mcp_connected=getattr(
                    self.handler, "_ensure_mcp_connected", None
                ),
                preview_text=self.handler._preview_text,
            )
        return await service.process_message(
            user_message,
            intermediate_callback=self.handler._send_intermediate_response,
        )

    async def process_scheduled_task(
        self, task_message: str, task_name: str = "Scheduled Task"
    ) -> str:
        service = getattr(self.handler, "_conversation_service", None)
        if not isinstance(service, ConversationService):
            service = ConversationService(
                config=getattr(self.handler, "config", None),
                memory=self.handler.memory,
                embedding_client=self.handler.embedding_client,
                llm_client=self.handler.llm_client,
                memory_search_tool=self.handler.memory_search_tool,
                mcp_client=getattr(self.handler, "mcp_client", None),
                ensure_mcp_connected=getattr(
                    self.handler, "_ensure_mcp_connected", None
                ),
                preview_text=self.handler._preview_text,
            )
        return await service.process_scheduled_task(
            task_message,
            task_name,
            intermediate_callback=self.handler._send_intermediate_response,
        )
