"""The LLM request path: admission → slot → deadline → retries → fallback → client.

An infrastructure module — it works from startup. The topics of the exercises live in the modules wired together here
(app/overload.py, app/llm/{limiter,call,retries,fallback,client}.py).

For every request it records: the outcome (`app.requests`), end-to-end time (`app.request.duration`),
LLM service time (`llm.call.duration`) and the response header
`Server-Timing: wait;dur=…, llm;dur=…, ttft;dur=…, total;dur=…` (ms) — read by k6 and check.py.
"""
from __future__ import annotations

import asyncio
import time

import anthropic
import httpx2
from fastapi import Request
from opentelemetry import trace

from . import config, overload, state, telemetry
from .errors import ClientDisconnected, DeadlineExceeded, Rejected
from .llm import LLMJob, LLMResult, call, fallback, limiter, retries


def mock_headers(request: Request | None) -> dict:
    """Passes the x-mock-* headers from the client's request to the mock (repeatable response times in tests)."""
    if request is None or not config.MOCK_HEADERS:
        return {}
    return {h: request.headers[h] for h in config.MOCK_HEADER_NAMES if h in request.headers}


def classify_exception(e: BaseException) -> str:
    if isinstance(e, Rejected):
        return "rejected"
    if isinstance(e, DeadlineExceeded):
        return "deadline_exceeded"
    if isinstance(e, (ClientDisconnected, asyncio.CancelledError)):
        return "cancelled"
    if isinstance(e, anthropic.RateLimitError):
        return "provider_rate_limited"
    if isinstance(e, (anthropic.APITimeoutError, httpx2.TimeoutException, TimeoutError)):
        return "provider_timeout"
    if isinstance(e, (anthropic.APIError, httpx2.HTTPError)):
        return "provider_error"
    return "error"


def record_outcome(request: Request | None, endpoint: str, request_class: str, outcome: str, t0: float, timings: dict) -> None:
    total = time.perf_counter() - t0
    timings["total"] = total
    state.OUTCOMES[(endpoint, request_class, outcome)] += 1
    telemetry.record(telemetry.C_REQUESTS, 1, endpoint=endpoint, request_class=request_class, outcome=outcome)
    telemetry.record(telemetry.H_REQUEST, total, endpoint=endpoint, request_class=request_class, outcome=outcome)
    span = trace.get_current_span()
    span.set_attribute("app.request_class", request_class)
    span.set_attribute("app.outcome", outcome)
    if request is not None:
        request.state.timings = timings


async def execute(request: Request | None, z: LLMJob) -> LLMResult:
    """Runs the LLM job through the whole path; raises exceptions mapped to HTTP in app/main.py."""
    t0 = time.perf_counter()
    timings: dict = {}
    outcome = "ok"
    try:
        overload.admit(z.request_class)
        async with limiter.slot(z.request_class, z.max_tokens, overload.max_wait(z.request_class)) as wait:
            timings["wait"] = wait
            t1 = time.perf_counter()
            provider = "?"
            llm_outcome = "ok"
            try:
                with telemetry.tracer.start_as_current_span("llm.call", attributes={"app.request_class": z.request_class}) as s:
                    w = await call.with_deadline(
                        request, z.request_class, lambda: retries.with_retries(lambda: fallback.invoke(z)))
                    provider = w.provider
                    s.set_attribute("llm.provider", w.provider)
                    s.set_attribute("gen_ai.usage.output_tokens", w.output_tokens)
            except BaseException as e:
                llm_outcome = classify_exception(e)
                raise
            finally:
                timings["llm"] = time.perf_counter() - t1
                telemetry.record(telemetry.H_CALL, timings["llm"], request_class=z.request_class, provider=provider,
                                 outcome=llm_outcome)
            if w.ttft_s is not None:
                timings["ttft"] = w.ttft_s
                telemetry.record(telemetry.H_TTFT, w.ttft_s, request_class=z.request_class)
        return w
    except BaseException as e:
        outcome = classify_exception(e)
        raise
    finally:
        record_outcome(request, z.endpoint, z.request_class, outcome, t0, timings)


def server_timing(timings: dict | None) -> str | None:
    if not timings:
        return None
    return ", ".join(f"{k};dur={v * 1000:.1f}" for k, v in timings.items() if v is not None)
