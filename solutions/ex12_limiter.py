"""[SOLUTION ex. 12 (includes 01, 06, 08) — copy to app/llm/limiter.py] LLM slots: how many calls at once (a semaphore) and at what rate (the provider limiter).

Ex. 01 — ✅ the slot wait time in the trace (llm.queue_wait span, llm.queue.wait_ms attribute) and in the metrics.
Ex. 06 — ✅ pool size from Little's law (F3: it was 4).
Ex. 08 — ✅ a rate limiter from the anthropic-ratelimit-* headers and retry-after (F4).
Ex. 12 — ✅ separate pools for the short and long classes (F18).

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
# ex. 12 (F18): a separate pool for multi-minute calls. A shared pool = head-of-line blocking:
#   long calls (60–300 s) hold slots for minutes and short ones wait behind them. The size of the long pool also
#   comes from Little's law: λ_long ≈ 0.1/s × W ≈ 150 s → ~15 in flight; we reject more quickly (app/overload.py)
#   or send them to the task queue (ex. 14). The sum of the pools ≤ the provider's capacity (the mock: 64).
SLOTS_LONG = int(os.environ.get("LLM_SLOTS_LONG", "16"))
_SEMAPHORES = {"short": asyncio.Semaphore(SLOTS), "long": asyncio.Semaphore(SLOTS_LONG)}


def semaphore(request_class: str) -> asyncio.Semaphore:
    return _SEMAPHORES[request_class]


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


class Bucket:
    """A token bucket "on our side", synchronized with the provider's headers.

    We learn the limit/min from `anthropic-ratelimit-*-limit`, and correct the level down to `*-remaining`
    (the provider knows better how much is left — e.g. when traffic also comes from other processes).
    """

    def __init__(self) -> None:
        self.limit: float | None = None      # per minute; None = not known yet
        self.level = 0.0
        self.t = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        if self.limit:
            self.level = min(self.limit, self.level + (now - self.t) * self.limit / 60.0)
        self.t = now

    def time_until(self, n: float) -> float:
        if not self.limit:
            return 0.0
        self._refill()
        n = min(n, self.limit)
        return 0.0 if self.level >= n else (n - self.level) * 60.0 / self.limit

    def take(self, n: float) -> None:
        if self.limit:
            self._refill()
            self.level -= n

    def sync(self, limit: int, remaining: int) -> None:
        self._refill()
        if self.limit != limit:
            self.limit = float(limit)
            self.level = float(remaining)
        else:
            self.level = min(self.level, float(remaining))


_REQUESTS = Bucket()        # requests / min (RPM)
_OUTPUT_TOKENS = Bucket()   # output tokens / min (OTPM) — the provider reserves max_tokens at the start
_paused_until = 0.0         # after a 429: everyone waits until retry-after
_order = asyncio.Lock()     # FIFO: whoever waited first gets the token first


async def pace(request_class: str, max_tokens: int) -> None:
    """ex. 08 (F4): wait until the provider limits allow the call — instead of collecting 429s.

    We learn the limits from the headers of the first responses (until then we do not limit — the first wave
    is held by the slot pool anyway). We do not wait for a "probe": a non-streaming response carries the headers only
    after the whole generation, so waiting for it would stall the start of every process (measured: +2.1 s).
    """
    async with _order:
        while True:
            wait_s = max(_paused_until - time.monotonic(), _REQUESTS.time_until(1), _OUTPUT_TOKENS.time_until(max_tokens))
            if wait_s <= 0:
                _REQUESTS.take(1)
                _OUTPUT_TOKENS.take(max_tokens)
                return
            await asyncio.sleep(min(wait_s, 1.0))


def update_from_headers(status: int, headers) -> None:
    """ex. 08: limits and remaining resources from the headers; a 429 → pause everyone until retry-after."""
    global _paused_until
    for bucket, name in ((_REQUESTS, "requests"), (_OUTPUT_TOKENS, "output-tokens")):
        lim = headers.get(f"anthropic-ratelimit-{name}-limit")
        remaining_hdr = headers.get(f"anthropic-ratelimit-{name}-remaining")
        if lim and remaining_hdr:
            bucket.sync(int(lim), int(remaining_hdr))
    if status == 429:
        retry_after = headers.get("retry-after")
        _paused_until = max(_paused_until, time.monotonic() + (float(retry_after) if retry_after else 1.0))
