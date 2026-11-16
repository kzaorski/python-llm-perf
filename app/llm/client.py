"""LLM clients (AsyncAnthropic) per request class and per provider.

Ex. 09 — retries: how many attempts the SDK makes (`max_retries`) BENEATH the app's retries (F5).
Ex. 10 — timeouts: what the SDK `timeout` is (connect/read/write/pool — limits PER OPERATION,
          read = idle time) and what the total deadline is (app/llm/call.py) (F6, F17).

Current state (deliberate flaws, measured in Block B):
- the short client: SDK default settings — `max_retries=2`, read timeout 600 s;
- the long client: "calls take up to a minute, so a 60 s timeout" + `max_retries=2`, a non-streaming call.
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
# F5 (ex. 09): the SDK retries 2× by default — and app/llm/retries.py retries once more on top of it.
# F6 (ex. 10): no sensible timeout — the default read is 600 s: a hung provider holds a slot for minutes.
SHORT = {d: _new(d) for d in BASE_URLS}
# F17 (ex. 10): a timeout shorter than the expected response time (60–300 s) + SDK retries:
#   every long call ends with an error after ~3×60 s, and the provider generates 3× (cost ×3).
LONG = {d: _new(d, timeout=60.0) for d in BASE_URLS}


def get_client(request_class: str, provider: str) -> anthropic.AsyncAnthropic:
    return (LONG if request_class == "long" else SHORT)[provider]


async def complete(z: LLMJob, provider: str = "a") -> LLMResult:
    """One Messages API call (non-streaming) to the given provider."""
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
