"""Platform-neutral adapter contracts used by the core runtime."""

from typing import Any, Protocol


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
