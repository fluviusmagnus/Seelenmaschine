"""Approval workflow service for dangerous tool actions."""

import asyncio
import html
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

from utils.logger import get_logger

logger = get_logger()


@dataclass
class PendingApprovalRequest:
    """Represents a dangerous action waiting for user approval."""

    tool_name: str
    arguments: Dict[str, Any]
    reason: str
    future: asyncio.Future
    created_at: float
    abort_reason: Optional[str] = None


class ApprovalService:
    """Manage pending dangerous actions that require user approval."""

    def __init__(self) -> None:
        self._approval_lock = asyncio.Lock()
        self._pending_request: Optional[PendingApprovalRequest] = None
        self._state_listener: Optional[
            Callable[[Optional[PendingApprovalRequest]], None]
        ] = None

    @property
    def lock(self) -> asyncio.Lock:
        """Expose the approval lock for serialized approval updates."""
        return self._approval_lock

    @property
    def pending_request(self) -> Optional[PendingApprovalRequest]:
        """Return the current pending approval request."""
        return self._pending_request

    def set_state_listener(
        self, listener: Callable[[Optional[PendingApprovalRequest]], None]
    ) -> None:
        """Register a callback for pending request state changes."""
        self._state_listener = listener

    def _update_pending_request(
        self, request: Optional[PendingApprovalRequest]
    ) -> None:
        self._pending_request = request
        if self._state_listener is not None:
            self._state_listener(request)

    async def request_approval(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        reason: str,
        *,
        send_message: Optional[Callable[[str, Optional[str]], Awaitable[None]]] = None,
        timeout_seconds: float = 600.0,
    ) -> bool:
        """Create a pending request, notify the user, and wait for a decision."""
        async with self._approval_lock:
            loop = asyncio.get_running_loop()
            pending_request = PendingApprovalRequest(
                tool_name=tool_name,
                arguments=dict(arguments),
                reason=reason,
                future=loop.create_future(),
                created_at=loop.time(),
            )
            self._update_pending_request(pending_request)

            args_str = html.escape(json.dumps(arguments, ensure_ascii=False)[:800])
            msg = (
                f"⚠️ <b>DANGEROUS ACTION DETECTED</b> ⚠️\n\n"
                f"<b>Tool:</b> <code>{html.escape(tool_name)}</code>\n"
                f"<b>Reason:</b> <code>{html.escape(reason)}</code>\n"
                f"<b>Arguments:</b>\n<pre>{args_str}</pre>\n\n"
                f"Reply <b>/approve</b> to execute.\n"
                f"Any other message will <b>ABORT</b> this action."
            )

            if send_message is not None:
                try:
                    await send_message(msg, "HTML")
                except Exception as e:
                    logger.error(f"Failed to send approval request: {e}")
                    self._update_pending_request(None)
                    return False

            logger.info(
                "Approval request created for dangerous action: "
                f"tool={tool_name}, reason={reason}, args={arguments}"
            )

            try:
                approved = await asyncio.wait_for(
                    pending_request.future, timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                approved = False
                logger.warning(
                    f"Approval request timed out: tool={tool_name}, reason={reason}"
                )
                if send_message is not None:
                    try:
                        await send_message("⏰ Approval timed out. Action aborted.", None)
                    except Exception:
                        pass
            finally:
                if self._pending_request is pending_request:
                    self._update_pending_request(None)

            return approved

    def approve_pending(self) -> Optional[PendingApprovalRequest]:
        """Approve the current pending action if one exists."""
        pending_request = self._pending_request
        if pending_request and not pending_request.future.done():
            pending_request.future.set_result(True)
            logger.info(
                "Approval received from user: "
                f"tool={pending_request.tool_name}, reason={pending_request.reason}"
            )
            return pending_request
        return None

    def abort_pending(
        self, reason: str = "User declined this action."
    ) -> Optional[PendingApprovalRequest]:
        """Abort the current pending action if one exists."""
        pending_request = self._pending_request
        if pending_request and not pending_request.future.done():
            pending_request.abort_reason = reason
            pending_request.future.set_result(False)
            logger.info(
                "Pending approval aborted: "
                f"tool={pending_request.tool_name}, reason={pending_request.reason}, "
                f"abort_reason={reason}"
            )
            return pending_request
        return None
