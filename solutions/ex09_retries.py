"""[SOLUTION ex. 09 — copy to app/llm/retries.py] Retries at the application level.

Ex. 09 (F5) ✅ — one retry layer (SDK: max_retries=0, app/llm/client.py):
- exponential backoff with FULL jitter: pause = U(0, min(limit, base·2^attempt)) — clients that
  got an error at the same moment do not come back together in the same wave;
- the provider's `retry-after` takes precedence (429/529 say when to come back);
- a retry budget: retries ≤ 20% of successful/all requests in the last window — in a mass outage
  we do not multiply traffic to the overloaded provider (you get ×1.2 instead of ×3);
- we do NOT retry timeouts: a provider that did not answer in time usually is still working on
  the previous attempt — a repeat doubles its load and our wait time (ex. 10, F17).
"""
from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from collections.abc import Awaitable, Callable

import anthropic
import httpx2

ATTEMPTS = 3                  # 1 + 2 retries
BASE_S = 0.5
LIMIT_S = 8.0
BUDGET = 0.2               # retries / requests in the window
WINDOW_S = 10.0

_requests: deque[float] = deque()
_retries: deque[float] = deque()


def _trim(d: deque, now: float) -> None:
    while d and d[0] < now - WINDOW_S:
        d.popleft()


def _budget_allows() -> bool:
    now = time.monotonic()
    _trim(_requests, now)
    _trim(_retries, now)
    return len(_retries) < max(1.0, BUDGET * len(_requests))


def _should_retry(e: Exception) -> bool:
    if isinstance(e, (anthropic.APITimeoutError, httpx2.TimeoutException)):
        return False                     # a timeout ≠ a transient error (see the docstring)
    return isinstance(e, (anthropic.RateLimitError, anthropic.OverloadedError, anthropic.InternalServerError,
                          anthropic.APIConnectionError))


def _pause(e: Exception, attempt: int) -> float:
    resp = getattr(e, "response", None)
    retry_after = resp.headers.get("retry-after") if resp is not None else None
    if retry_after:
        try:
            return float(retry_after) + random.uniform(0, 0.5)
        except ValueError:
            pass
    return random.uniform(0, min(LIMIT_S, BASE_S * 2 ** attempt))


async def with_retries(fn: Callable[[], Awaitable]):
    _requests.append(time.monotonic())
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return await fn()
        except Exception as e:
            if attempt == ATTEMPTS or not _should_retry(e) or not _budget_allows():
                raise
            _retries.append(time.monotonic())
            await asyncio.sleep(_pause(e, attempt))
