"""An LLM call with a total deadline and cancellation when the client disconnects.

Ex. 10 — TODO (F6, F16): for now a call lasts as long as the provider wants:
- no total deadline: the SDK `timeout` is a limit PER OPERATION (read = idle time), so a stream
  or a hung provider can hold a slot for minutes;
- no cancellation: when the client (k6, a browser, a proxy) disconnects, the app keeps waiting for the LLM,
  holds the semaphore slot, and the provider generates (and bills) tokens that nobody will receive.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request


async def with_deadline(request: Request | None, request_class: str, fn: Callable[[], Awaitable]):
    """TODO ex. 10: a deadline per class (asyncio.timeout) + abort when the client disconnects.

    After the deadline is exceeded raise errors.DeadlineExceeded, after a disconnect — errors.ClientDisconnected.
    `request` may be None (a call from outside HTTP, e.g. the queue worker).
    """
    return await fn()
