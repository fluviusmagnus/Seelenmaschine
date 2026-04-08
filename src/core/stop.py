"""Cooperative stop control for active conversation/tool loops."""

from typing import Optional


class ToolLoopAbortedError(Exception):
    """Raised when the current tool loop is stopped by user request."""


class StopController:
    """Track and signal stop requests for the single active conversation loop."""

    STOP_ALL_FURTHER_REASON = (
        "Error: The user rejected this action and requested that all further steps stop."
    )

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
