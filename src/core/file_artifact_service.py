"""Core-owned helpers for persisting tool/MCP binary artifacts."""

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

    def build_saved_artifact_message(
        self,
        artifact: Dict[str, Any],
    ) -> str:
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