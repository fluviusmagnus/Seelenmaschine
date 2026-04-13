"""Core-owned file artifact persistence and delivery policy services."""

from __future__ import annotations

import base64
import binascii
import mimetypes
import re
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from utils.logger import get_logger

logger = get_logger()


class FileArtifactService:
    """Persist binary-like tool outputs into media/tool_artifacts."""

    _BASE64_SEQUENCE_PATTERN = re.compile(r"[A-Za-z0-9+/=]{512,}")

    def __init__(self, *, config: Any):
        self.config = config

    def _artifacts_dir(self) -> Path:
        target = Path(self.config.MEDIA_DIR) / "tool_artifacts"
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _sanitize_filename(self, filename: str) -> str:
        sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._")
        return sanitized or "artifact"

    def _guess_extension(
        self,
        *,
        mime_type: Optional[str] = None,
        filename: Optional[str] = None,
        default_extension: str = ".bin",
    ) -> str:
        if filename:
            suffix = Path(filename).suffix
            if suffix:
                return suffix

        if mime_type:
            guessed = mimetypes.guess_extension(mime_type, strict=False)
            if guessed:
                return guessed

        return default_extension

    def _build_target_path(
        self,
        *,
        filename: Optional[str] = None,
        mime_type: Optional[str] = None,
        prefix: str = "artifact",
        default_extension: str = ".bin",
    ) -> Path:
        safe_prefix = self._sanitize_filename(prefix)
        safe_name = self._sanitize_filename(filename or safe_prefix)
        extension = self._guess_extension(
            mime_type=mime_type,
            filename=filename,
            default_extension=default_extension,
        )
        stem = Path(safe_name).stem or safe_prefix
        unique_name = f"{stem}_{uuid4().hex[:8]}{extension}"
        return self._artifacts_dir() / unique_name

    def build_saved_artifact_message(self, artifact: Dict[str, Any]) -> str:
        lines = ["[Tool Returned File]"]
        for key in (
            "path",
            "filename",
            "mime_type",
            "size_bytes",
            "source",
            "content_kind",
        ):
            value = artifact.get(key)
            if value not in (None, ""):
                lines.append(f"{key}: {value}")
        return "\n".join(lines)

    def save_bytes_artifact(
        self,
        data: bytes,
        *,
        filename: Optional[str] = None,
        mime_type: Optional[str] = None,
        source: str,
        content_kind: str,
        prefix: str = "artifact",
    ) -> Dict[str, Any]:
        target = self._build_target_path(
            filename=filename,
            mime_type=mime_type,
            prefix=prefix,
        )
        target.write_bytes(data)
        return {
            "path": str(target.resolve()),
            "filename": target.name,
            "mime_type": mime_type or mimetypes.guess_type(str(target))[0] or "",
            "size_bytes": len(data),
            "source": source,
            "content_kind": content_kind,
        }

    def save_base64_artifact(
        self,
        base64_text: str,
        *,
        filename: Optional[str] = None,
        mime_type: Optional[str] = None,
        source: str,
        content_kind: str,
        prefix: str = "artifact",
    ) -> Dict[str, Any]:
        normalized = re.sub(r"\s+", "", base64_text)
        data = base64.b64decode(normalized, validate=False)
        return self.save_bytes_artifact(
            data,
            filename=filename,
            mime_type=mime_type,
            source=source,
            content_kind=content_kind,
            prefix=prefix,
        )

    def maybe_persist_text_base64(
        self,
        text: str,
        *,
        source: str,
        filename: Optional[str] = None,
        mime_type: Optional[str] = None,
        content_kind: str = "base64_text",
        prefix: str = "artifact",
    ) -> Optional[str]:
        if not text:
            return None

        match = self._BASE64_SEQUENCE_PATTERN.search(text)
        if not match:
            return None

        candidate = match.group(0)
        try:
            artifact = self.save_base64_artifact(
                candidate,
                filename=filename,
                mime_type=mime_type,
                source=source,
                content_kind=content_kind,
                prefix=prefix,
            )
        except (ValueError, binascii.Error) as error:
            logger.debug(f"Skipping invalid base64 artifact candidate: {error}")
            return None
        except Exception as error:
            logger.warning(f"Failed to persist base64 artifact: {error}")
            return None

        return self.build_saved_artifact_message(artifact)


class FileDeliveryService:
    """Own file delivery policy and path checks, but not platform transport."""

    def __init__(self, *, config: Any):
        self.config = config

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
        *,
        platform_label: str = "adapter",
    ) -> str:
        """Build assistant-role system-tone event text for sent files."""
        message_lines = [
            f"[System Event] Assistant has sent a file via {platform_label}.",
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

    def prepare_file_delivery(
        self,
        *,
        file_path: str,
        caption: Optional[str] = None,
        file_type: str = "auto",
    ) -> Dict[str, Any]:
        """Validate a local file path and return normalized delivery inputs."""
        resolved_path = self.resolve_file_path(file_path)
        if not resolved_path.exists():
            raise FileNotFoundError(f"File not found: {resolved_path}")
        if not resolved_path.is_file():
            raise ValueError(f"Path is not a file: {resolved_path}")
        if not self.is_allowed_file_path(resolved_path):
            raise ValueError(
                "File path is outside allowed directories (workspace/media)"
            )
        return {
            "resolved_path": self._format_saved_path(resolved_path),
            "caption": caption,
            "file_type": file_type,
        }