"""Claims service desk assistant — a FastAPI app (port 8060).

Run locally:        uvicorn app.main:app --port 8060
gunicorn variant:   gunicorn -c gunicorn.conf.py   (ex. 07; port 8062)

Endpoints (request class in parentheses; short = seconds, long = 60–300 s):
  POST /claims/{n}/summary          claim summary (short)                          — ex. 01–03, 06, 08–12
  POST /claims/{n}/classify         classification (short)                         — ex. 04 (app/classification.py)
  POST /claims/{n}/letter           letter from a template (short)                 — ex. 05 (app/templates.py)
  POST /claims/{n}/reply/stream     customer reply as an SSE stream (short)        — ex. 13 (app/stream.py)
  POST /claims/{n}/analysis         claim file analysis (LONG)                     — ex. 10, 12
  POST /claims/{n}/summary/async    summary through the task queue → {"task": id}  — ex. 14 (app/tasks.py)
  GET  /jobs/{id}                   state/result of a task from the queue
  GET  /faq?q=…                     answer to a frequently asked question, Redis cache — ex. 15 (app/cache.py)
  POST /claims/{n}/priority         claim priority, batched                        — ex. 16 (app/batch.py)
  GET  /health, GET /diag, GET /diag/ping

The x-mock-ttft-ms / x-mock-total-s / x-mock-output-tokens headers of the request go to the mock LLM
(repeatable response times in k6 tests). Every LLM response has a Server-Timing header
(wait / llm / ttft / total in ms).
"""
from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager

import anthropic
import httpx2
import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import config, telemetry

telemetry.configure()

from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # noqa: E402

from . import batch, cache, classification, data, pipeline, state, stream, tasks, templates  # noqa: E402
from .errors import ClientDisconnected, DeadlineExceeded, NotImplementedTODO, Rejected  # noqa: E402
from .llm import LLMJob, client  # noqa: E402

_redis = aioredis.from_url(config.REDIS_URL)
_http = httpx2.AsyncClient(timeout=2.0)
START = time.time()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    monitor = asyncio.create_task(telemetry.monitor_loop())
    await tasks.broker.startup()          # task queue producer (ex. 14)
    try:
        yield
    finally:
        monitor.cancel()
        await tasks.broker.shutdown()


app = FastAPI(title="claims-assistant (python-llm-perf)", version="1.0", lifespan=lifespan)
for r in (classification.router, templates.router, stream.router, cache.router, batch.router):
    app.include_router(r)


class ServerTiming:
    """Pure ASGI middleware: appends Server-Timing from request.state.timings (scope["state"]).

    Deliberately NOT @app.middleware("http") (BaseHTTPMiddleware): it replaces `receive`, so
    `request.is_disconnected()` in the handler does not see the client disconnecting (measured in Block B).
    """

    def __init__(self, app_):
        self.app = app_

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_timing(msg):
            if msg["type"] == "http.response.start":
                st = pipeline.server_timing((scope.get("state") or {}).get("timings"))
                headers = list(msg.get("headers", []))
                if st and not any(k.lower() == b"server-timing" for k, _ in headers):
                    headers.append((b"server-timing", st.encode()))
                    msg = {**msg, "headers": headers}
            await send(msg)
        await self.app(scope, receive, send_with_timing)


app.add_middleware(ServerTiming)


FastAPIInstrumentor.instrument_app(app, excluded_urls="/diag/ping")


# ---------------------------------------------------------------- errors → HTTP
def _error(request: Request, status: int, outcome: str, description: str, headers: dict | None = None) -> JSONResponse:
    h = dict(headers or {})
    st = pipeline.server_timing(getattr(request.state, "timings", None))
    if st:
        h["server-timing"] = st
    return JSONResponse({"outcome": outcome, "error": description}, status_code=status, headers=h)


@app.exception_handler(Rejected)
async def _rejected(request: Request, e: Rejected):
    return _error(request, 503, "rejected", e.reason, {"retry-after": str(max(1, round(e.retry_after)))})


@app.exception_handler(DeadlineExceeded)
async def _deadline_exceeded(request: Request, e: DeadlineExceeded):
    return _error(request, 504, "deadline_exceeded", str(e))


@app.exception_handler(ClientDisconnected)
async def _client_disconnected(request: Request, e: ClientDisconnected):
    return _error(request, 499, "cancelled", "the client disconnected")


@app.exception_handler(NotImplementedTODO)
async def _todo(request: Request, e: NotImplementedTODO):
    return _error(request, 501, "todo", f"Do exercise {e.exercise} first: {e.what}")


@app.exception_handler(anthropic.APIError)
async def _llm(request: Request, e: anthropic.APIError):
    outcome = pipeline.classify_exception(e)
    status = {"provider_rate_limited": 503, "provider_timeout": 504}.get(outcome, 502)
    return _error(request, status, outcome, f"{type(e).__name__}: {str(e)[:200]}")


@app.exception_handler(httpx2.HTTPError)
async def _http_err(request: Request, e: httpx2.HTTPError):
    outcome = pipeline.classify_exception(e)
    return _error(request, 504 if outcome == "provider_timeout" else 502, outcome, type(e).__name__)


# ---------------------------------------------------------------- domain endpoints
SYSTEM = "You are a claims adjuster's assistant at an insurance company. You write factually, in English."


@app.post("/claims/{n}/summary")
async def summary(n: int, request: Request):
    z = data.claim(n)
    w = await pipeline.execute(request, LLMJob(
        request_class="short", endpoint="summary", max_tokens=200, system=SYSTEM,
        prompt=f"Summarize the claim for the adjuster in 3 sentences.\n{data.describe_for_llm(z)}",
        headers=pipeline.mock_headers(request)))
    return {"claim": z["id"], "summary": w.text, "provider": w.provider, "tokens": w.output_tokens}


@app.post("/claims/{n}/analysis")
async def analysis(n: int, request: Request):
    """Analysis of the whole claim file — a multi-minute call (class `long`)."""
    z = data.claim(n)
    w = await pipeline.execute(request, LLMJob(
        request_class="long", endpoint="analysis", max_tokens=4000, system=SYSTEM,
        prompt=f"Analyze the complete claim file: validity of the claim, risks, missing documents, recommendation.\n"
               f"{data.describe_for_llm(z)}",
        headers=pipeline.mock_headers(request)))
    return {"claim": z["id"], "analysis_chars": len(w.text), "provider": w.provider, "tokens": w.output_tokens}


@app.post("/claims/{n}/summary/async")
async def summary_async(n: int, request: Request):
    t = await tasks.background_summary.kiq(n, pipeline.mock_headers(request), time.time())
    return {"task": t.task_id}


@app.get("/jobs/{task_id}")
async def task_status(task_id: str):
    if not await tasks.broker.result_backend.is_result_ready(task_id):
        return {"task": task_id, "state": "pending_or_running"}
    r = await tasks.broker.result_backend.get_result(task_id)
    if r.is_err:
        return {"task": task_id, "state": "error", "error": str(r.error)[:200]}
    return {"task": task_id, "state": "done", "result": r.return_value}


# ---------------------------------------------------------------- health / diagnostics
async def _probe(coro) -> dict:
    t0 = time.perf_counter()
    try:
        await coro
        return {"ok": True, "ms": round((time.perf_counter() - t0) * 1000, 1)}
    except Exception as e:  # noqa: BLE001 — health reports, it does not raise
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}


async def _llm_health():
    r = await _http.get(config.LLM_BASE_URL.rstrip("/") + "/health")
    r.raise_for_status()


@app.get("/health")
async def health():
    local = "127.0.0.1" in config.LLM_BASE_URL or "localhost" in config.LLM_BASE_URL
    deps = {"redis": await _probe(_redis.ping()),
            "llm": await _probe(_llm_health()) if local else {"ok": True, "skipped": "external provider"}}
    return {"status": "ok" if all(d["ok"] for d in deps.values()) else "degraded", "deps": deps,
            "server": telemetry.VARIANT, "pid": os.getpid(), "claims": data.count()}


@app.get("/diag/ping")
async def ping():
    """No I/O and no telemetry — the response time = the responsiveness of the event loop."""
    return {"ok": True}


@app.get("/diag")
async def diag():
    """Process state: the LLM queue per class, loop lag, outcomes and HTTP attempts since start, client configuration."""
    def describe_client(k):
        t = k.timeout
        return {"max_retries": k.max_retries,
                "timeout": {"connect": t.connect, "read": t.read} if hasattr(t, "read") else t}
    return {
        "pid": os.getpid(), "server": telemetry.VARIANT, "uptime_s": round(time.time() - START, 1),
        "queue": {k: s.as_dict() for k, s in state.STATE.items()},
        "loop_lag_max_10s_ms": round(state.LOOP_LAG.recent_max() * 1000, 1),
        "outcomes": [{"endpoint": e, "request_class": k, "outcome": w, "n": n} for (e, k, w), n in sorted(state.OUTCOMES.items())],
        "http_attempts": [{"provider": d, "status": s, "n": n} for (d, s), n in sorted(state.HTTP_ATTEMPTS.items())],
        "clients": {cls_name: describe_client(client.get_client(cls_name, "a")) for cls_name in state.REQUEST_CLASSES},
    }
