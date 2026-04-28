"""Human-in-the-loop approval and stop control services."""

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

from texts import ApprovalTexts
from utils.logger import get_logger

logger = get_logger()


class ApprovalTimeoutError(Exception):
    """Raised when a dangerous action approval request times out."""


@dataclass
class ApprovalDecision:
    """Represents the final outcome of an approval request."""

    approved: bool
    abort_reason: Optional[str] = None
    user_message: Optional[str] = None


@dataclass
class PendingApprovalRequest:
    """Represents a dangerous action waiting for user approval."""

    tool_name: str
    arguments: Dict[str, Any]
    reason: str
    future: asyncio.Future
    created_at: float
    abort_reason: Optional[str] = None
    abort_message: Optional[str] = None


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
    ) -> ApprovalDecision:
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

            msg = ApprovalTexts.request_approval(tool_name, arguments, reason)

            if send_message is not None:
                try:
                    await send_message(msg, "HTML")
                except Exception as e:
                    logger.error(f"Failed to send approval request: {e}")
                    self._update_pending_request(None)
                    return ApprovalDecision(
                        approved=False,
                        abort_reason=ApprovalTexts.DELIVERY_FAILED_ABORT_REASON,
                    )

            logger.info(
                "Approval request created for dangerous action: "
                f"tool={tool_name}, reason={reason}, args={arguments}"
            )

            try:
                decision = await asyncio.wait_for(
                    pending_request.future, timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"Approval request timed out: tool={tool_name}, reason={reason}"
                )
                if send_message is not None:
                    try:
                        await send_message(ApprovalTexts.TIMEOUT_NOTICE, None)
                    except Exception:
                        pass
                raise ApprovalTimeoutError(ApprovalTexts.TIMEOUT_ABORT_ERROR)
            finally:
                if self._pending_request is pending_request:
                    self._update_pending_request(None)

            return decision

    def approve_pending(self) -> Optional[PendingApprovalRequest]:
        """Approve the current pending action if one exists."""
        pending_request = self._pending_request
        if pending_request and not pending_request.future.done():
            pending_request.future.set_result(ApprovalDecision(approved=True))
            logger.info(
                "Approval received from user: "
                f"tool={pending_request.tool_name}, reason={pending_request.reason}"
            )
            return pending_request
        return None

    def abort_pending(
        self,
        reason: str = ApprovalTexts.USER_DECLINED_REASON,
        user_message: Optional[str] = None,
    ) -> Optional[PendingApprovalRequest]:
        """Abort the current pending action if one exists."""
        pending_request = self._pending_request
        if pending_request and not pending_request.future.done():
            pending_request.abort_reason = reason
            pending_request.abort_message = user_message
            pending_request.future.set_result(
                ApprovalDecision(
                    approved=False,
                    abort_reason=reason,
                    user_message=user_message,
                )
            )
            logger.info(
                "Pending approval aborted: "
                f"tool={pending_request.tool_name}, reason={pending_request.reason}, "
                f"abort_reason={reason}, abort_message={user_message!r}"
            )
            return pending_request
        return None


class ToolLoopAbortedError(Exception):
    """Raised when the current tool loop is stopped by user request."""


class StopController:
    """Track and signal stop requests for the single active conversation loop."""

    STOP_ALL_FURTHER_REASON = ApprovalTexts.STOP_ALL_FURTHER_REASON

    def __init__(self) -> None:
        self._running = False
        self._stop_requested = False
        self._stop_reason: Optional[str] = None

    def begin_run(self) -> None:
        """Mark a new conversation/tool loop as running and clear stale stop state."""
        self._running = True
        self._stop_requested = False
        self._stop_reason = None

    def end_run(self) -> None:
        """Mark the active run as finished and clear stop state."""
        self._running = False
        self._stop_requested = False
        self._stop_reason = None

    def request_stop(self, reason: str = STOP_ALL_FURTHER_REASON) -> bool:
        """Request a cooperative stop for the current run."""
        if not self._running:
            return False
        self._stop_requested = True
        self._stop_reason = reason
        return True

    def check_stop_requested(self) -> None:
        """Raise if the current run has been asked to stop."""
        if self._stop_requested:
            raise ToolLoopAbortedError(
                self._stop_reason or self.STOP_ALL_FURTHER_REASON
            )

    def has_running_run(self) -> bool:
        """Return whether a conversation/tool loop is currently active."""
        return self._running

    def is_stop_requested(self) -> bool:
        """Return whether a stop has been requested for the active run."""
        return self._stop_requested
