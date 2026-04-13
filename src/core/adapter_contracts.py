"""Platform-neutral adapter contracts used by the core runtime."""

from typing import Any, Awaitable, Callable, Optional, Protocol


class AdapterApprovalDelegate(Protocol):
    """Approval capabilities required by tool execution runtime."""

    async def request_approval(
        self, tool_name: str, arguments: dict, reason: str
    ) -> Any:
        ...

    async def notify_approved_action_finished(self, tool_name: str, result: str) -> None:
        ...

    async def notify_approved_action_failed(
        self, tool_name: str, error: Exception
    ) -> None:
        ...


class AdapterRuntimeCapabilities:
    """Platform-neutral adapter capabilities required by the core runtime."""

    def __init__(
        self,
        *,
        preview_text: Callable[[Optional[str], int], str],
        send_file_to_user: Callable[..., Any],
        send_status_message: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> None:
        self.preview_text = preview_text
        self.send_file_to_user = send_file_to_user
        self.send_status_message = send_status_message