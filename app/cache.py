"""Answers to frequently asked customer questions (FAQ) with a Redis cache — endpoint GET /faq?q=…

Ex. 15 (F10): a cache without single-flight. When a key expires (or does not exist yet), each of N
concurrent identical questions sees a "miss" and calls the LLM ITSELF — N calls instead of one
(cache stampede). With a popular question that is a wave of traffic to the provider every TTL seconds.
TODO ex. 15: single-flight — only one call per key; the others wait for its result.
"""
from __future__ import annotations

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


async def get_or_compute(k: str, q: str, request: Request) -> tuple[str, str]:
    """Returns (answer, source) — source: hit | miss."""
    v = await r.get(k)
    if v is not None:
        telemetry.record(telemetry.C_CACHE, 1, outcome="hit")
        return v, "hit"
    telemetry.record(telemetry.C_CACHE, 1, outcome="miss")
    v = await compute(q, request)          # F10: every "miss" calls the LLM separately
    await r.set(k, v, ex=TTL_S)
    return v, "miss"


@router.get("/faq")
async def faq(q: str, request: Request):
    v, source = await get_or_compute(cache_key(q), q, request)
    return {"question": q, "answer": v, "cache": source}
