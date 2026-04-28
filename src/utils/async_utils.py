import asyncio
from typing import Awaitable, Callable, Optional, TypeVar


T = TypeVar("T")


def ensure_not_in_async_context(error_message: str) -> None:
    """Raise a clear error if a sync wrapper is called from async code."""
    try:
        asyncio.get_running_loop()
        raise RuntimeError(error_message)
    except RuntimeError as error:
        if "no running event loop" not in str(error).lower():
            raise


def run_sync(
    coroutine_factory: Callable[[], Awaitable[T]],
    loop_provider: Optional[Callable[[], asyncio.AbstractEventLoop]] = None,
) -> T:
    """Run an async coroutine from sync code using the provided event loop."""
    loop = loop_provider() if loop_provider is not None else get_or_create_event_loop()
    return loop.run_until_complete(coroutine_factory())


def get_or_create_event_loop() -> asyncio.AbstractEventLoop:
    """Return a usable event loop for sync bootstrap wrappers."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop
