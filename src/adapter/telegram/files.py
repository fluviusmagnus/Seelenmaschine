import asyncio
import mimetypes
import re
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from adapter.telegram.delivery import send_segmented_text, typing_indicator
from telegram import Update

from utils.logger import get_logger

logger = get_logger()


class TelegramFiles:
    """Handle Telegram file uploads and proactive file sending."""

    _FILE_EXTRACTORS = (
        ("document", "document", lambda item: item, lambda item: item.file_name),
        ("photo", "photo", lambda item: item[-1], lambda item: None),
        ("video", "video", lambda item: item, lambda item: item.file_name),
        ("audio", "audio", lambda item: item, lambda item: item.file_name),
        ("voice", "voice", lambda item: item, lambda item: None),
    )
    _DEFAULT_MIME_TYPES = {
        "photo": "image/jpeg",
    }

    def __init__(self, config: Any, memory: Any):
        self.config = config
        self.memory = memory

    async def handle_file(
        self,
        update: Update,
        context: Any,
        process_message: Callable[[str], Awaitable[str]],
        format_response_for_telegram: Callable[[str], str],
        split_message_into_segments: Callable[[str], list[str]],
        preview_text: Callable[[str, int], str],
        format_exception_for_user: Callable[[Exception], str],
    ) -> None:
        """Save the uploaded file and process it as a synthetic user event."""
        if not update.effective_user or not update.message:
            return

        user_id = update.effective_user.id
        if user_id != self.config.TELEGRAM_USER_ID:
            await update.message.reply_text("Unauthorized access.")
            logger.warning(f"Unauthorized file from user {user_id}")
            return

        file_info = self.extract_file_info_from_update(update)
        if not file_info:
            logger.warning("Received file handler update without supported attachment")
            await update.message.reply_text("Unsupported file type.")
            return

        logger.info(
            f"Received {file_info['file_type']} from user {user_id}: "
            f"{file_info.get('original_name') or file_info['file_unique_id']}"
        )

        try:
            async with typing_indicator(
                lambda: context.bot.send_chat_action(
                    chat_id=update.effective_chat.id, action="typing"
                ),
                "Typing indicator failed during file handling",
            ):
                destination = self.build_media_file_path(
                    original_name=file_info.get("original_name"),
                    file_unique_id=file_info["file_unique_id"],
                    mime_type=file_info.get("mime_type"),
                    file_type=file_info["file_type"],
                )
                saved_path = await self.download_telegram_file(
                    context, file_info["file_id"], destination
                )

                user_message = self.build_received_file_event_message(
                    file_info, saved_path
                )
                logger.info(
                    "Built synthetic file event message for LLM: "
                    f"{preview_text(user_message)}"
                )
                response = await process_message(user_message)
                logger.info(
                    "Prepared final text for Telegram file reply: "
                    f"{preview_text(response)}"
                )

                formatted_response = format_response_for_telegram(response)
                segments = split_message_into_segments(formatted_response)

                logger.debug(f"File response split into {len(segments)} segments")
                logger.info(
                    f"Sending {len(segments)} Telegram segment(s) for file message"
                )

                await send_segmented_text(
                    segments=segments,
                    send_html=lambda segment: update.message.reply_text(
                        segment, parse_mode="HTML"
                    ),
                    send_plain=update.message.reply_text,
                    html_warning_template=(
                        "HTML parsing failed for file segment {index}, "
                        "sending as plain text: {error}"
                    ),
                    preview_text=preview_text,
                    debug_prefix="Sending Telegram file segment",
                )
        except Exception as error:
            logger.error(f"Error handling file: {error}", exc_info=True)
            await update.message.reply_text(
                "Sorry, an error occurred while processing your file.\n\n"
                f"Details: {format_exception_for_user(error)}"
            )

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Strip path separators and control characters from Telegram filenames."""
        sanitized = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", filename).strip(" .")
        return sanitized or "file"

    @staticmethod
    def guess_extension(
        original_name: Optional[str], mime_type: Optional[str], file_type: str
    ) -> str:
        """Infer a stable file extension for saved Telegram uploads."""
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
        """Build a unique destination path for an uploaded Telegram media file."""
        base_name = self.sanitize_filename(original_name or file_type)
        base_stem = Path(base_name).stem or file_type
        extension = self.guess_extension(original_name, mime_type, file_type)
        timestamp = asyncio.get_running_loop().time()
        unique_part = f"{int(timestamp * 1000)}_{file_unique_id}"
        filename = f"{base_stem}_{unique_part}{extension}"
        return self.config.MEDIA_DIR / filename

    def _build_file_info(
        self,
        *,
        file_type: str,
        item: Any,
        caption: Optional[str],
        original_name: Optional[str],
    ) -> Dict[str, Any]:
        """Normalize Telegram attachment metadata into the internal file shape."""
        return {
            "file_id": item.file_id,
            "file_unique_id": item.file_unique_id,
            "file_type": file_type,
            "original_name": original_name,
            "mime_type": getattr(item, "mime_type", None)
            or self._DEFAULT_MIME_TYPES.get(file_type),
            "file_size": getattr(item, "file_size", None),
            "caption": caption,
        }

    def extract_file_info_from_update(
        self, update: Update
    ) -> Optional[Dict[str, Any]]:
        """Extract the supported attachment metadata from a Telegram update."""
        if not update.message:
            return None
        message = update.message
        caption = getattr(message, "caption", None)

        for message_attr, file_type, item_selector, name_selector in self._FILE_EXTRACTORS:
            raw_item = getattr(message, message_attr, None)
            if not raw_item:
                continue

            item = item_selector(raw_item)
            return self._build_file_info(
                file_type=file_type,
                item=item,
                caption=caption,
                original_name=name_selector(item),
            )
        return None

    async def download_telegram_file(
        self, context: Any, file_id: str, destination: Path
    ) -> Path:
        """Download a Telegram attachment to the target destination."""
        telegram_file = await context.bot.get_file(file_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        await telegram_file.download_to_drive(custom_path=str(destination))
        return destination

    def build_received_file_event_message(
        self, file_info: Dict[str, Any], saved_path: Path
    ) -> str:
        """Describe an uploaded file as a synthetic system event for the LLM."""
        original_name = file_info.get("original_name") or saved_path.name
        message_lines = [
            "[System Event] The user has sent a file.",
            f"File type: {file_info['file_type']}",
            f"Original filename: {original_name}",
            f"Saved to: {self.format_saved_media_path(saved_path)}",
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

    def format_saved_media_path(self, saved_path: Path) -> str:
        """Format saved path for user-facing/system-facing messages."""
        return str(saved_path.resolve())

    def _allowed_telegram_file_dirs(self) -> list[Path]:
        """Return the directories that proactive file sending may access."""
        return [
            self.config.WORKSPACE_DIR.resolve(),
            self.config.MEDIA_DIR.resolve(),
        ]

    def resolve_telegram_file_path(self, file_path: str) -> Path:
        """Resolve a tool-provided file path against the workspace."""
        candidate = Path(file_path)
        if not candidate.is_absolute():
            candidate = self.config.WORKSPACE_DIR / candidate
        return candidate.resolve()

    def is_allowed_telegram_file_path(self, resolved_path: Path) -> bool:
        """Check that the path is inside the allowed directories."""
        for allowed_dir in self._allowed_telegram_file_dirs():
            try:
                resolved_path.relative_to(allowed_dir)
                return True
            except ValueError:
                continue

        return False

    @staticmethod
    async def _send_file_by_method(
        telegram_bot: Any,
        delivery_method: str,
        file_obj: Any,
        send_kwargs: Dict[str, Any],
    ) -> None:
        """Dispatch a file object through the matching Telegram API."""
        senders = {
            "photo": telegram_bot.send_photo,
            "video": telegram_bot.send_video,
            "audio": telegram_bot.send_audio,
            "voice": telegram_bot.send_voice,
            "document": telegram_bot.send_document,
        }
        sender = senders.get(delivery_method, telegram_bot.send_document)
        file_kwarg = {
            "photo": "photo",
            "video": "video",
            "audio": "audio",
            "voice": "voice",
            "document": "document",
        }.get(delivery_method, "document")
        await sender(**{file_kwarg: file_obj, **send_kwargs})

    def detect_telegram_delivery_method(
        self, resolved_path: Path, file_type: str = "auto"
    ) -> str:
        """Detect which Telegram API should be used for the file."""
        if file_type != "auto":
            return file_type

        suffix = resolved_path.suffix.lower()
        mime_type, _ = mimetypes.guess_type(str(resolved_path))

        if mime_type:
            if mime_type.startswith("image/"):
                return "photo"
            if mime_type.startswith("video/"):
                return "video"
            if mime_type.startswith("audio/"):
                if suffix in {".ogg", ".oga", ".opus"}:
                    return "voice"
                return "audio"

        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            return "photo"
        if suffix in {".mp4", ".mov", ".mkv", ".webm", ".avi"}:
            return "video"
        if suffix in {".mp3", ".wav", ".m4a", ".flac", ".aac"}:
            return "audio"
        if suffix in {".ogg", ".oga", ".opus"}:
            return "voice"

        return "document"

    def build_sent_file_event_message(
        self,
        sent_path: Path,
        delivery_method: str,
        caption: Optional[str] = None,
    ) -> str:
        """Build assistant-role system-tone event text for sent files."""
        message_lines = [
            "[System Event] Assistant has sent a file via Telegram.",
            f"Delivery method: {delivery_method}",
            f"Filename: {sent_path.name}",
            f"Path: {self.format_saved_media_path(sent_path)}",
        ]

        mime_type, _ = mimetypes.guess_type(str(sent_path))
        if mime_type:
            message_lines.append(f"MIME type: {mime_type}")

        if caption:
            message_lines.append(f"Caption: {caption}")

        return "\n".join(message_lines)

    async def send_file_to_user(
        self,
        telegram_bot: Any,
        file_path: str,
        caption: Optional[str] = None,
        file_type: str = "auto",
    ) -> Dict[str, Any]:
        """Send a local file to the Telegram user and record the event in memory."""
        if telegram_bot is None:
            raise RuntimeError("Telegram bot is not available for proactive file sending")

        resolved_path = self.resolve_telegram_file_path(file_path)
        if not resolved_path.exists():
            raise FileNotFoundError(f"File not found: {resolved_path}")
        if not resolved_path.is_file():
            raise ValueError(f"Path is not a file: {resolved_path}")
        if not self.is_allowed_telegram_file_path(resolved_path):
            raise ValueError("File path is outside allowed directories (workspace/media)")

        delivery_method = self.detect_telegram_delivery_method(
            resolved_path, file_type=file_type
        )

        send_kwargs: Dict[str, Any] = {"chat_id": self.config.TELEGRAM_USER_ID}
        if caption:
            send_kwargs["caption"] = caption

        with open(resolved_path, "rb") as file_obj:
            await self._send_file_by_method(
                telegram_bot, delivery_method, file_obj, send_kwargs
            )

        event_text = self.build_sent_file_event_message(
            resolved_path, delivery_method, caption
        )
        await self.memory.add_assistant_message_async(event_text)

        logger.info(
            f"Sent file to Telegram user via {delivery_method}: {resolved_path.name}"
        )
        return {
            "status": "sent",
            "delivery_method": delivery_method,
            "resolved_path": self.format_saved_media_path(resolved_path),
            "caption": caption,
        }
