import asyncio
from typing import Any, Awaitable, Callable, Dict

from utils.logger import get_logger

logger = get_logger()


class SendFileTool:
    """Tool for sending a local file to the current user."""

    def __init__(
        self,
        send_callback: Callable[..., Awaitable[Dict[str, Any]] | Dict[str, Any]],
    ):
        """Initialize with a callback that performs the concrete file delivery."""
        self._send_callback = send_callback

    @property
    def name(self) -> str:
        return "send_file"

    @property
    def description(self) -> str:
        return """Send a local file to the current user.

WHEN TO USE:
- User asks you to send/export/deliver a generated file
- You created or found a file in the workspace and should proactively send it
- The result is best delivered as an attachment instead of pasted text

IMPORTANT:
- file_path must point to an existing local file in the workspace/media area
- Prefer file_type='auto' unless you are certain about the media type
- Use caption for a short delivery note shown with the file"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Local path to the file to send. Relative paths are resolved from the workspace directory.",
                },
                "caption": {
                    "type": "string",
                    "description": "Optional caption to attach to the file.",
                },
                "file_type": {
                    "type": "string",
                    "enum": ["auto", "document", "photo", "video", "audio", "voice"],
                    "description": "How the file should be sent. Use 'auto' to detect from MIME type and extension.",
                },
            },
            "required": ["file_path"],
        }

    async def execute(self, **kwargs) -> str | Dict[str, Any]:
        """Send a file through the injected callback."""
        file_path = kwargs.get("file_path")
        caption = kwargs.get("caption")
        file_type = kwargs.get("file_type", "auto")

        if not file_path:
            return "Error: file_path is required"

        if file_type not in {"auto", "document", "photo", "video", "audio", "voice"}:
            return (
                "Error: file_type must be one of auto, document, photo, video, "
                "audio, or voice"
            )

        try:
            result = self._send_callback(
                file_path=file_path,
                caption=caption,
                file_type=file_type,
            )
            if asyncio.iscoroutine(result):
                result = await result

            if isinstance(result, dict):
                lines = ["✓ File sent to user"]
                delivery_method = result.get("delivery_method")
                resolved_path = result.get("resolved_path")
                sent_caption = result.get("caption")

                if delivery_method:
                    lines.append(f"Delivery method: {delivery_method}")
                if resolved_path:
                    lines.append(f"Path: {resolved_path}")
                if sent_caption:
                    lines.append(f"Caption: {sent_caption}")

                return {
                    "result": "\n".join(lines),
                    "event_message": result.get("event_message"),
                }

            return str(result)
        except Exception as e:
            logger.error(f"Failed to send file: {e}")
            return f"Error sending file: {e}"
