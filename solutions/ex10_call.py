"""[SOLUTION ex. 10 — copy to app/llm/call.py] An LLM call with a deadline and cancellation.

Ex. 10 ✅ (F6, F16):
- a TOTAL deadline per class (`asyncio.timeout`) — independent of the SDK timeouts, which are per operation;
  after it is exceeded the task is cancelled: the connection to the provider closes, and the provider stops generating;
- a disconnect guard: every 0.5 s `request.is_disconnected()`; when the client has gone — we cancel the call,
  the semaphore slot and the provider-side slot come back right away, instead of after minutes of generating "for nobody".
"""
from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import Awaitable, Callable

from fastapi import Request

from ..errors import ClientDisconnected, DeadlineExceeded

# Short: a response SLO of seconds → 30 s is the "useless anyway" boundary.
# Long: a 60–300 s tail (requirement) + headroom for waiting at the provider → 330 s; k6/proxies must allow more.
DEADLINE_S = {"short": float(os.environ.get("DEADLINE_SHORT_S", "30")),
              "long": float(os.environ.get("DEADLINE_LONG_S", "330"))}


async def _wait_for_disconnect(request: Request) -> None:
    while not await request.is_disconnected():
        await asyncio.sleep(0.5)


async def with_deadline(request: Request | None, request_class: str, fn: Callable[[], Awaitable]):
    deadline = DEADLINE_S[request_class]
    work = asyncio.ensure_future(fn())
    guard = asyncio.ensure_future(_wait_for_disconnect(request)) if request is not None else None
    try:
        async with asyncio.timeout(deadline):
            await asyncio.wait({work} | ({guard} if guard else set()), return_when=asyncio.FIRST_COMPLETED)
    except TimeoutError:
        work.cancel()
        with contextlib.suppress(BaseException):
            await work
        raise DeadlineExceeded("LLM call", deadline) from None
    except asyncio.CancelledError:
        work.cancel()
        raise
    finally:
        if guard is not None:
            guard.cancel()
    if work.done():
        return work.result()
    work.cancel()                       # the client disconnected
    with contextlib.suppress(BaseException):
        await work
    raise ClientDisconnected()
