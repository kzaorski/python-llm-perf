"""LLM slots: how many calls at once (a semaphore) and at what rate (the provider limiter).

Ex. 01 — TODO: show the slot wait time in the trace and in the metrics.
Ex. 06 — pool size (F3): how many slots you need at a given traffic (Little's law: L = λ·W).
Ex. 08 — TODO: a rate limiter against the provider limits (F4: none for now — an avalanche of 429s).
Ex. 12 — separate pools for the short and long classes (F18: one shared pool for now).

`slot()` is used by app/pipeline.py:
    async with limiter.slot(request_class, max_tokens, max_wait):
        ... LLM call ...
"""
from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager

from .. import state, telemetry
from ..errors import Rejected

# F3 (ex. 06): 4 slots "just in case" — too few at ~20 requests/s and ~1.3 s per call.
SLOTS = int(os.environ.get("LLM_SLOTS", "4"))
# F18 (ex. 12): one pool for short and multi-minute calls.
_SEMAPHORE = asyncio.Semaphore(SLOTS)


def semaphore(request_class: str) -> asyncio.Semaphore:
    return _SEMAPHORE


@asynccontextmanager
async def slot(request_class: str, max_tokens: int, max_wait: float | None = None):
    """Takes an LLM slot for the class; `max_wait` (s) — after that time Rejected (ex. 12)."""
    st = state.STATE[request_class]
    sem = semaphore(request_class)
    tok = st.start_waiting()
    t0 = time.perf_counter()
    t0_ns = time.time_ns()
    try:
        if max_wait is None:
            await sem.acquire()
        else:
            try:
                await asyncio.wait_for(sem.acquire(), max_wait)
            except TimeoutError:
                raise Rejected("slot_wait_timeout", retry_after=max_wait) from None
        try:
            await pace(request_class, max_tokens)
        except BaseException:
            sem.release()
            raise
    finally:
        st.stop_waiting(tok)
    wait = time.perf_counter() - t0
    # TODO ex. 01: the slot wait time (`wait`) is invisible for now.
    #   1) a `llm.queue_wait` span from t0_ns to now — a SIBLING of the call span, not its parent:
    #      telemetry.tracer.start_span(..., start_time=t0_ns) + .end() (without activating the context),
    #   2) a `llm.queue.wait_ms` attribute on the request span (trace.get_current_span()),
    #   3) the telemetry.H_QUEUE_WAIT histogram with the request_class attribute (telemetry.record(...)).
    st.inflight += 1
    try:
        yield wait
    finally:
        st.inflight -= 1
        sem.release()


async def pace(request_class: str, max_tokens: int) -> None:
    """TODO ex. 08 (F4): wait until the provider limit (requests/min, output tokens/min) allows the call.

    For now we limit nothing — with traffic above the limit the provider answers 429.
    """
    return None


def update_from_headers(status: int, headers) -> None:
    """TODO ex. 08: called from the HTTP hook for every response of provider `a`.

    Headers: anthropic-ratelimit-{requests,output-tokens}-{limit,remaining,reset}, retry-after (on 429).
    """
    return None
