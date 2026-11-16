"""Retries at the application level.

Ex. 09 (F5): we retry fast (a constant 100 ms, no backoff and no jitter) up to 3 attempts — ON TOP of the SDK retries
(`max_retries=2` in app/llm/client.py). With an overloaded provider, one user request turns
into up to 3×3 = 9 HTTP attempts, sent in waves at the same rhythm by all clients at once.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import anthropic

ATTEMPTS = 3
PAUSE_S = 0.1


async def with_retries(fn: Callable[[], Awaitable]):
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return await fn()
        except (anthropic.RateLimitError, anthropic.OverloadedError, anthropic.InternalServerError,
                anthropic.APIConnectionError):
            # 429, 529 overloaded, 5xx; APIConnectionError also covers timeouts (APITimeoutError)
            if attempt == ATTEMPTS:
                raise
            await asyncio.sleep(PAUSE_S)
