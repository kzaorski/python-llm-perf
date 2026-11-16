"""[SOLUTION ex. 06 (includes 01) — copy to app/llm/limiter.py] LLM slots: how many calls at once (a semaphore) and at what rate (the provider limiter).

Ex. 01 — ✅ the slot wait time in the trace (llm.queue_wait span, llm.queue.wait_ms attribute) and in the metrics.
Ex. 06 — ✅ pool size from Little's law (F3: it was 4).
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

from opentelemetry import trace

from .. import state, telemetry
from ..errors import Rejected

# ex. 06 (F3): pool size from Little's law: L = λ · W.
#   Target traffic λ ≈ 20 requests/s, call time W ≈ 1.3 s (p50 of a summary on the mock; p99 ~1.8 s)
#   → 26 calls in flight on average. Headroom for the tail and brief spikes: 32. More will not help when
#   the provider is the constraint (capacity/limits) — then the queue moves to it (ex. 08, 12).
SLOTS = int(os.environ.get("LLM_SLOTS", "32"))
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
    # ex. 01: the wait time is visible in the trace and in the metrics.
    # We create the wait span WITHOUT activating it (start_span, not start_as_current_span): it is a sibling
    # of the `llm.call` span, not its parent — otherwise the call would look like part of the wait.
    s = telemetry.tracer.start_span("llm.queue_wait", start_time=t0_ns,
                                    attributes={"app.request_class": request_class, "llm.waiting_at_entry": st.waiting_count})
    s.end()
    trace.get_current_span().set_attribute("llm.queue.wait_ms", round(wait * 1000, 1))
    telemetry.record(telemetry.H_QUEUE_WAIT, wait, request_class=request_class)
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
