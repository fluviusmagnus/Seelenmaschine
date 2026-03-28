"""Core-owned file delivery policy and side effects."""

import mimetypes
from pathlib import Path
from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger()


class FileDeliveryService:
    """Own file delivery policy, path checks, and memory side effects."""

    def __init__(self, *, config: Any, memory: Any, telegram_files: Any):
        self.config = config
        self.memory = memory
        self.telegram_files = telegram_files

    def _allowed_dirs(self) -> list[Path]:
        """Return the directories that proactive file sending may access."""
        return [
            self.config.WORKSPACE_DIR.resolve(),
            self.config.MEDIA_DIR.resolve(),
        ]

    def resolve_file_path(self, file_path: str) -> Path:
        """Resolve a tool-provided file path against the workspace."""
        candidate = Path(file_path)
        if not candidate.is_absolute():
            candidate = self.config.WORKSPACE_DIR / candidate
        return candidate.resolve()

    def is_allowed_file_path(self, resolved_path: Path) -> bool:
        """Check that the path is inside the allowed directories."""
        for allowed_dir in self._allowed_dirs():
            try:
                resolved_path.relative_to(allowed_dir)
                return True
            except ValueError:
                continue
        return False

    def _format_saved_path(self, saved_path: Path) -> str:
        """Format saved path for user-facing/system-facing messages."""
        return str(saved_path.resolve())

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
            f"Path: {self._format_saved_path(sent_path)}",
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
        """Send a local file and record the core-side delivery event."""
        resolved_path = self.resolve_file_path(file_path)
        if not resolved_path.exists():
            raise FileNotFoundError(f"File not found: {resolved_path}")
        if not resolved_path.is_file():
            raise ValueError(f"Path is not a file: {resolved_path}")
        if not self.is_allowed_file_path(resolved_path):
            raise ValueError(
                "File path is outside allowed directories (workspace/media)"
            )

        delivery_method = await self.telegram_files.send_local_file(
            telegram_bot=telegram_bot,
            resolved_path=resolved_path,
            caption=caption,
            file_type=file_type,
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
            "resolved_path": self._format_saved_path(resolved_path),
            "caption": caption,
        }
