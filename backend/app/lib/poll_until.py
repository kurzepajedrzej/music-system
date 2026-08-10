import asyncio
import logging
import time
from typing import Awaitable, Callable

log = logging.getLogger(__name__)


async def poll_until(
    check: Callable[[], Awaitable[bool]],
    interval: float = 0.2,
    timeout: float = 5.0,
    label: str = "",
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if await check():
                return True
        except Exception:
            pass  # one bad attempt shouldn't abort the whole poll — just retry
        await asyncio.sleep(interval)
    if label:
        log.warning("poll_until timed out after %.1fs waiting for: %s", timeout, label)
    return False
