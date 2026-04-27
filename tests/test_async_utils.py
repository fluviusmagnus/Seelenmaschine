import asyncio

import pytest

from utils.async_utils import run_sync


def test_run_sync_does_not_retry_business_runtime_error():
    calls = 0

    async def fail_once() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("application failure")

    loop = asyncio.new_event_loop()
    try:
        with pytest.raises(RuntimeError, match="application failure"):
            run_sync(lambda: fail_once(), lambda: loop)
    finally:
        loop.close()

    assert calls == 1
