import asyncio
from typing import Any, Awaitable, Callable, Dict

from texts import ToolTexts
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
        return ToolTexts.SendFile.DESCRIPTION

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": ToolTexts.SendFile.PARAMETER_DESCRIPTIONS["file_path"],
                },
                "caption": {
                    "type": "string",
                    "description": ToolTexts.SendFile.PARAMETER_DESCRIPTIONS["caption"],
                },
                "file_type": {
                    "type": "string",
                    "enum": ["auto", "document", "photo", "video", "audio", "voice"],
                    "description": ToolTexts.SendFile.PARAMETER_DESCRIPTIONS["file_type"],
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
            return ToolTexts.error("file_path is required")

        if file_type not in {"auto", "document", "photo", "video", "audio", "voice"}:
            return ToolTexts.SendFile.FILE_TYPE_ERROR

        try:
            result = self._send_callback(
                file_path=file_path,
                caption=caption,
                file_type=file_type,
            )
            if asyncio.iscoroutine(result):
                result = await result

            if isinstance(result, dict):
                return {
                    "result": ToolTexts.SendFile.sent_result(
                        delivery_method=result.get("delivery_method"),
                        resolved_path=result.get("resolved_path"),
                        caption=result.get("caption"),
                    ),
                    "event_message": result.get("event_message"),
                }

            return str(result)
        except Exception as e:
            logger.error(f"Failed to send file: {e}")
            return f"Error sending file: {e}"
