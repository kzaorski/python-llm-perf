"""[SOLUTION ex. 11 — copy to app/llm/fallback.py] A fallback provider with a circuit breaker.

Ex. 11 (F12) ✅ — the states of the circuit breaker for provider `a`:
- CLOSED: traffic goes to `a`; we count consecutive failures;
- OPEN: after FAILURE_THRESHOLD consecutive failures, for OPEN_DURATION_S we do not ask `a` at all — straight to `b`
  (the request does not pay `a`'s timeout, and `a` gets time to recover);
- HALF-OPEN: after the open time ONE probe request goes to `a`; success closes the breaker,
  failure opens it again.
The breaker state: the `llm.cb.state` attribute on the `llm.call` span and in /diag (a counter of state changes).
"""
from __future__ import annotations

import os
import time

import anthropic
from opentelemetry import trace

from .. import config, state
from . import LLMJob, LLMResult, client

OUTAGE_ERRORS = (anthropic.APIConnectionError, anthropic.InternalServerError)
FAILURE_THRESHOLD = int(os.environ.get("CB_THRESHOLD", "5"))
OPEN_DURATION_S = float(os.environ.get("CB_OPEN_S", "30"))


def _is_outage(e: Exception) -> bool:
    if isinstance(e, anthropic.OverloadedError):
        return False   # 529 overloaded = overload, not an outage — a fallback would move the storm to `b`
    return isinstance(e, OUTAGE_ERRORS)


class CircuitBreaker:
    def __init__(self) -> None:
        self.state = "closed"
        self.failures = 0
        self.open_until = 0.0
        self.probe_in_flight = False

    def _set_state(self, new_state: str) -> None:
        if new_state != self.state:
            state.OUTCOMES[("cb", "a", f"{self.state}->{new_state}")] += 1
            self.state = new_state

    def should_try_a(self) -> bool:
        if self.state == "closed":
            return True
        if self.state == "open" and time.monotonic() >= self.open_until:
            self._set_state("half_open")
        if self.state == "half_open" and not self.probe_in_flight:
            self.probe_in_flight = True
            return True
        return False

    def success(self) -> None:
        self.failures = 0
        self.probe_in_flight = False
        self._set_state("closed")

    def failure(self) -> None:
        self.failures += 1
        self.probe_in_flight = False
        if self.state == "half_open" or self.failures >= FAILURE_THRESHOLD:
            self.open_until = time.monotonic() + OPEN_DURATION_S
            self._set_state("open")


BREAKER = CircuitBreaker()


async def invoke(z: LLMJob) -> LLMResult:
    trace.get_current_span().set_attribute("llm.cb.state", BREAKER.state)
    if not config.LLM_FALLBACK:
        return await client.complete(z, "a")
    if BREAKER.should_try_a():
        try:
            w = await client.complete(z, "a")
            BREAKER.success()
            return w
        except Exception as e:
            if not _is_outage(e):
                BREAKER.probe_in_flight = False
                raise
            BREAKER.failure()
    return await client.complete(z, "b")
