import asyncio
from typing import Awaitable, Callable, TypeVar


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
    loop_provider: Callable[[], asyncio.AbstractEventLoop],
) -> T:
    """Run an async coroutine from sync code using the provided event loop."""
    loop = loop_provider()
    try:
        return loop.run_until_complete(coroutine_factory())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coroutine_factory())