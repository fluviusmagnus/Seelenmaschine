import asyncio
import mimetypes
import random
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from telegram import Update

from utils.logger import get_logger

logger = get_logger()


class TelegramFiles:
    """Handle Telegram file uploads and proactive file sending."""

    def __init__(self, config: Any, memory: Any):
        self.config = config
        self.memory = memory

    async def handle_file(
        self,
        update: Update,
        context: Any,
        extract_file_info: Callable[[Update], Dict[str, Any] | None],
        build_media_file_path: Callable[..., Path],
        download_telegram_file: Callable[[Any, str, Path], Awaitable[Path]],
        build_file_event_message: Callable[[Dict[str, Any], Path], str],
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

        file_info = extract_file_info(update)
        if not file_info:
            logger.warning("Received file handler update without supported attachment")
            await update.message.reply_text("Unsupported file type.")
            return

        logger.info(
            f"Received {file_info['file_type']} from user {user_id}: "
            f"{file_info.get('original_name') or file_info['file_unique_id']}"
        )

        async def _keep_typing_indicator() -> None:
            while True:
                try:
                    await context.bot.send_chat_action(
                        chat_id=update.effective_chat.id, action="typing"
                    )
                    await asyncio.sleep(3)
                except Exception as error:
                    logger.warning(
                        f"Typing indicator failed during file handling: {error}"
                    )
                    await asyncio.sleep(3)

        try:
            typing_task = asyncio.create_task(_keep_typing_indicator())
            try:
                destination = build_media_file_path(
                    original_name=file_info.get("original_name"),
                    file_unique_id=file_info["file_unique_id"],
                    mime_type=file_info.get("mime_type"),
                    file_type=file_info["file_type"],
                )
                saved_path = await download_telegram_file(
                    context, file_info["file_id"], destination
                )

                user_message = build_file_event_message(file_info, saved_path)
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

                for index, segment in enumerate(segments):
                    try:
                        logger.debug(
                            f"Sending Telegram file segment {index + 1}/{len(segments)}: "
                            f"{preview_text(segment)}"
                        )
                        await update.message.reply_text(segment, parse_mode="HTML")
                        if index < len(segments) - 1:
                            await asyncio.sleep(random.uniform(1.0, 2.0))
                    except Exception as error:
                        logger.warning(
                            "HTML parsing failed for file segment "
                            f"{index + 1}, sending as plain text: {error}"
                        )
                        await update.message.reply_text(segment)
            finally:
                typing_task.cancel()
                try:
                    await typing_task
                except asyncio.CancelledError:
                    pass
        except Exception as error:
            logger.error(f"Error handling file: {error}", exc_info=True)
            await update.message.reply_text(
                "Sorry, an error occurred while processing your file.\n\n"
                f"Details: {format_exception_for_user(error)}"
            )

    def format_saved_media_path(self, saved_path: Path) -> str:
        """Format saved path for user-facing/system-facing messages."""
        return str(saved_path.resolve())

    def resolve_telegram_file_path(self, file_path: str) -> Path:
        """Resolve a tool-provided file path against the workspace."""
        candidate = Path(file_path)
        if not candidate.is_absolute():
            candidate = self.config.WORKSPACE_DIR / candidate
        return candidate.resolve()

    def is_allowed_telegram_file_path(self, resolved_path: Path) -> bool:
        """Check that the path is inside the allowed directories."""
        allowed_dirs = [
            self.config.WORKSPACE_DIR.resolve(),
            self.config.MEDIA_DIR.resolve(),
        ]

        for allowed_dir in allowed_dirs:
            try:
                resolved_path.relative_to(allowed_dir)
                return True
            except ValueError:
                continue

        return False

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
            if delivery_method == "photo":
                await telegram_bot.send_photo(photo=file_obj, **send_kwargs)
            elif delivery_method == "video":
                await telegram_bot.send_video(video=file_obj, **send_kwargs)
            elif delivery_method == "audio":
                await telegram_bot.send_audio(audio=file_obj, **send_kwargs)
            elif delivery_method == "voice":
                await telegram_bot.send_voice(voice=file_obj, **send_kwargs)
            else:
                await telegram_bot.send_document(document=file_obj, **send_kwargs)

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
