"""[SOLUTION ex. 10 (includes 09) — copy to app/llm/client.py] LLM clients (AsyncAnthropic) per request class and per provider.

Ex. 09 — retries: how many attempts the SDK makes (`max_retries`) BENEATH the app's retries (F5).
Ex. 10 — timeouts: what the SDK `timeout` is (connect/read/write/pool — limits PER OPERATION,
          read = idle time) and what the total deadline is (app/llm/call.py) (F6, F17).

Current state (deliberate flaws, measured in Block B):
- the short client: ✅ ex. 09 `max_retries=0`; ✅ ex. 10 timeouts per SLO (read 15 s);
- the long client: ✅ ex. 10 a stream, read 60 s = idle time, `max_retries=0`.
"""
from __future__ import annotations

import os
import time

import anthropic
import httpx2

from .. import config, state, telemetry
from . import LLMJob, LLMResult, limiter

BASE_URLS = {"a": config.LLM_BASE_URL, "b": config.LLM_FALLBACK_BASE_URL}
# Size of the httpx2 connection pool per provider (0 = the SDK default: 1000). Ex. 06 — the "pool < semaphore" variant.
CONNECTIONS = int(os.environ.get("LLM_CONNECTIONS", "0"))


# ---------------------------------------------------------------- measurement infrastructure (do not change)
def _http(provider: str, **kw):
    """The SDK's httpx2 client with hooks that count EVERY HTTP attempt (including retries inside the SDK)."""

    async def on_request(request):
        telemetry.record(telemetry.C_ATTEMPTS, 1, provider=provider)

    async def on_response(response):
        state.HTTP_ATTEMPTS[(provider, response.status_code)] += 1
        telemetry.record(telemetry.C_RESPONSES, 1, provider=provider, status=str(response.status_code))
        if provider == "a":
            limiter.update_from_headers(response.status_code, response.headers)

    if CONNECTIONS:     # ex. 06: httpx2 connection pool smaller than the semaphore → waiting in the pool / PoolTimeout
        kw["limits"] = httpx2.Limits(max_connections=CONNECTIONS, max_keepalive_connections=CONNECTIONS)
    return anthropic.DefaultAsyncHttpxClient(event_hooks={"request": [on_request], "response": [on_response]},
                                             **kw)


def _new(provider: str, **kw) -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(base_url=BASE_URLS[provider], api_key=config.LLM_API_KEY,
                                    http_client=_http(provider), **kw)


# ---------------------------------------------------------------- client configuration (ex. 09, 10)
# ex. 09 (F5): ONE retry layer — in the app (app/llm/retries.py: backoff + jitter + budget).
#   The SDK does not retry (max_retries=0), so one request = at most 1 + 2 attempts, not 3 × 3.
# ex. 10 (F6): timeouts of the short class per its SLO, not "just in case". Without streaming, read = the time until the whole
#   response; a summary on the mock has p99 ≈ 2 s, real Claude ~1–4 s, so 15 s of silence is a provider
#   outage, not the tail of the distribution. connect 3 s (local network/TLS), pool 5 s. The total is guarded by the deadline
#   in app/llm/call.py (short: 30 s) — read is NOT the total limit.
TIMEOUT_SHORT = anthropic.Timeout(connect=3.0, read=15.0, write=10.0, pool=5.0)
SHORT = {d: _new(d, max_retries=0, timeout=TIMEOUT_SHORT) for d in BASE_URLS}
# ex. 10 (F17): long calls (60–300 s) go as a STREAM. Then the read timeout is an IDLE limit between
#   events (tokens or a `ping` every ~15 s from the provider), not the time of the whole response — 60 s of silence
#   is an outage. No SDK retries: repeating a 4-minute generation after a timeout means double the cost
#   and as much waiting again; the app decides about retrying (a 330 s deadline in call.py).
TIMEOUT_LONG = anthropic.Timeout(connect=3.0, read=60.0, write=10.0, pool=5.0)
LONG = {d: _new(d, max_retries=0, timeout=TIMEOUT_LONG) for d in BASE_URLS}


def get_client(request_class: str, provider: str) -> anthropic.AsyncAnthropic:
    return (LONG if request_class == "long" else SHORT)[provider]


async def complete(z: LLMJob, provider: str = "a") -> LLMResult:
    """One Messages API call to the given provider (long ones as a stream, ex. 10)."""
    if z.request_class == "long":
        return await _complete_streaming(z, provider)
    k = get_client(z.request_class, provider)
    t0 = time.perf_counter()
    kw = {"system": z.system} if z.system else {}
    m = await k.messages.create(model=config.LLM_MODEL, max_tokens=z.max_tokens,
                                messages=[{"role": "user", "content": z.prompt}],
                                extra_headers=z.headers or None, **kw)
    text = "".join(b.text for b in m.content if getattr(b, "type", "") == "text")
    return LLMResult(text, m.usage.input_tokens, m.usage.output_tokens, provider, time.perf_counter() - t0)


async def stream(z: LLMJob, provider: str = "a"):
    """A stream of text chunks (async generator) — used by app/stream.py (ex. 13)."""
    k = get_client(z.request_class, provider)
    kw = {"system": z.system} if z.system else {}
    async with k.messages.stream(model=config.LLM_MODEL, max_tokens=z.max_tokens,
                                 messages=[{"role": "user", "content": z.prompt}],
                                 extra_headers=z.headers or None, **kw) as s:
        async for text in s.text_stream:
            yield text


async def _complete_streaming(z: LLMJob, provider: str) -> LLMResult:
    """ex. 10: a multi-minute call through a stream — the read timeout = idle time, we measure TTFT.

    Note: a timeout DURING the stream is a raw httpx2.ReadTimeout (not anthropic.APITimeoutError).
    """
    k = get_client(z.request_class, provider)
    t0 = time.perf_counter()
    ttft = None
    parts = []
    kw = {"system": z.system} if z.system else {}
    async with k.messages.stream(model=config.LLM_MODEL, max_tokens=z.max_tokens,
                                 messages=[{"role": "user", "content": z.prompt}],
                                 extra_headers=z.headers or None, **kw) as s:
        async for text in s.text_stream:
            if ttft is None:
                ttft = time.perf_counter() - t0
            parts.append(text)
        m = await s.get_final_message()
    return LLMResult("".join(parts), m.usage.input_tokens, m.usage.output_tokens, provider,
                     time.perf_counter() - t0, ttft)
