"""[SOLUTION ex. 15 — copy to app/cache.py] Answers to frequently asked customer questions (FAQ) with a Redis cache — endpoint GET /faq?q=…

Ex. 15 (F10): a cache without single-flight. When a key expires (or does not exist yet), each of N
concurrent identical questions sees a "miss" and calls the LLM ITSELF — N calls instead of one
(cache stampede). With a popular question that is a wave of traffic to the provider every TTL seconds.
✅ ex. 15: single-flight (an in-process Future, across processes a SET NX lock in Redis).
"""
from __future__ import annotations

import asyncio
import hashlib
import os

import redis.asyncio as aioredis
from fastapi import APIRouter, Request

from . import config, pipeline, telemetry
from .llm import LLMJob

router = APIRouter()
r = aioredis.from_url(config.REDIS_URL, decode_responses=True)
TTL_S = int(os.environ.get("FAQ_TTL_S", "60"))


def cache_key(q: str) -> str:
    return "faq:" + hashlib.sha1(q.strip().lower().encode()).hexdigest()[:16]


async def compute(q: str, request: Request) -> str:
    z = LLMJob(request_class="short", endpoint="faq", max_tokens=300,
               prompt=f"Answer the insurance customer's question: {q}",
               headers=pipeline.mock_headers(request))
    return (await pipeline.execute(request, z)).text


_inflight: dict[str, asyncio.Future] = {}
LOCK_S = 30            # a cross-process lock: longer than the short-class deadline (30 s)


async def get_or_compute(k: str, q: str, request: Request) -> tuple[str, str]:
    """ex. 15 (F10) ✅ single-flight: one LLM call per key, the rest wait for its result.

    1) in the process: a dict key → Future (the first one computes, the others `await` the same Future);
    2) across processes (e.g. several gunicorn workers): a lock in Redis `SET … NX PX` — whoever did not
       get the lock waits until the value appears in the cache (polling every 50 ms).
    Returns (answer, source) — source: hit | miss | shared (waited for someone else's call).
    """
    v = await r.get(k)
    if v is not None:
        telemetry.record(telemetry.C_CACHE, 1, outcome="hit")
        return v, "hit"
    if k in _inflight:
        telemetry.record(telemetry.C_CACHE, 1, outcome="shared")
        return await asyncio.shield(_inflight[k]), "shared"
    fut = asyncio.get_running_loop().create_future()
    _inflight[k] = fut
    try:
        if await r.set(k + ":lock", "1", nx=True, px=LOCK_S * 1000):
            try:
                telemetry.record(telemetry.C_CACHE, 1, outcome="miss")
                v = await compute(q, request)
                await r.set(k, v, ex=TTL_S)
                source = "miss"
            finally:
                await r.delete(k + ":lock")
        else:                                   # another process is computing — we wait for the result in the cache
            telemetry.record(telemetry.C_CACHE, 1, outcome="shared")
            source = "shared"
            for _ in range(LOCK_S * 20):
                v = await r.get(k)
                if v is not None:
                    break
                await asyncio.sleep(0.05)
            else:
                v = await compute(q, request)    # the lock owner died — we compute it ourselves
        fut.set_result(v)
        return v, source
    except BaseException as e:
        if not fut.done():
            fut.set_exception(e)
            fut.exception()                     # mark as retrieved (no asyncio warnings)
        raise
    finally:
        _inflight.pop(k, None)


@router.get("/faq")
async def faq(q: str, request: Request):
    v, source = await get_or_compute(cache_key(q), q, request)
    return {"question": q, "answer": v, "cache": source}
