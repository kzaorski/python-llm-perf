"""[SOLUTION ex. 13 — copy to app/stream.py] A reply to the customer as a stream (SSE) — endpoint POST /claims/{n}/reply/stream.

SSE events: `event: delta` (a text chunk), at the end `event: end` (statistics), on error `event: error`.

Ex. 13 (F9): the handler collects the WHOLE LLM response and only then sends it to the client in one event.
The provider returns the first token after ~0.5 s, but the client sees the first byte after the entire generation
(client TTFT ≈ total time). The `llm.ttft` metric (from the provider's side) looks fine — it lies about the UX.
✅ ex. 13: chunks are sent right away; a client disconnect aborts the generation.
"""
from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from . import data, overload, pipeline, telemetry
from .llm import LLMJob, client, limiter

router = APIRouter()


def sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


def first_chunk(timings: dict, t0: float) -> None:
    """Measurement infrastructure: the moment the first chunk is sent to the client (TTFT from the client's side)."""
    timings["first"] = time.perf_counter() - t0
    telemetry.record(telemetry.H_FIRST_CHUNK, timings["first"])


def make_job(n: int, request: Request) -> LLMJob:
    z = data.claim(n)
    return LLMJob(request_class="short", endpoint="reply-stream", max_tokens=700,
                  prompt=f"Write a reply to the customer about the claim.\n{data.describe_for_llm(z)}",
                  headers=pipeline.mock_headers(request))


@router.post("/claims/{n}/reply/stream")
async def reply_stream(n: int, request: Request):
    z = make_job(n, request)

    async def generate():
        t0 = time.perf_counter()
        timings: dict = {}
        outcome = "ok"
        try:
            overload.admit(z.request_class)
            async with limiter.slot(z.request_class, z.max_tokens, overload.max_wait(z.request_class)) as wait:
                timings["wait"] = wait
                t1 = time.perf_counter()
                n_chunks = 0
                # ex. 13 (F9) ✅: every chunk goes straight to the client — client TTFT ≈ provider TTFT.
                async for text in client.stream(z):
                    if n_chunks == 0:
                        timings["ttft"] = time.perf_counter() - t1
                        telemetry.record(telemetry.H_TTFT, timings["ttft"], request_class=z.request_class)
                    n_chunks += 1
                    if n_chunks == 1:
                        first_chunk(timings, t0)
                    yield sse("delta", {"text": text})
                    # Starlette (ASGI ≥ 2.4) will not stop the generator on a disconnect by itself — we check
                    if n_chunks % 20 == 0 and await request.is_disconnected():
                        outcome = "cancelled"
                        return
                timings["llm"] = time.perf_counter() - t1
            yield sse("end", {k: round(v * 1000, 1) for k, v in timings.items()})
        except (GeneratorExit, asyncio.CancelledError, OSError):
            outcome = "cancelled"     # the client disconnected
            raise
        except Exception as e:
            outcome = pipeline.classify_exception(e)
            yield sse("error", {"outcome": outcome, "error": type(e).__name__})
        finally:
            pipeline.record_outcome(None, z.endpoint, z.request_class, outcome, t0, timings)

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"cache-control": "no-cache"})
