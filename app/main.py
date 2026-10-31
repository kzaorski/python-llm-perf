"""Asystent biura obsługi zgłoszeń szkodowych — aplikacja FastAPI (szkielet Bloku A).

Uruchom lokalnie:  uvicorn app.main:app --port 8060
Wariant gunicorn:  gunicorn app.main:app -k uvicorn_worker.UvicornWorker -w 2 -b 127.0.0.1:8062

Na tym etapie działa tylko /health (sprawdza Redis i atrapę LLM). Endpointy domenowe
(streszczenie, klasyfikacja, odpowiedź do klienta, kolejka) dochodzą w kolejnych blokach.
"""
import time

import httpx2
import redis.asyncio as aioredis
from fastapi import FastAPI

from . import config

app = FastAPI(title="claims-assistant (python-llm-perf)", version="0.1")
_redis = aioredis.from_url(config.REDIS_URL)
_http = httpx2.AsyncClient(timeout=2.0)


async def _probe(name: str, coro) -> dict:
    t0 = time.perf_counter()
    try:
        await coro
        return {"ok": True, "ms": round((time.perf_counter() - t0) * 1000, 1)}
    except Exception as e:  # noqa: BLE001 — health raportuje, nie rzuca
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}


async def _llm_health():
    r = await _http.get(config.LLM_BASE_URL.rstrip("/") + "/health")
    r.raise_for_status()


@app.get("/health")
async def health():
    deps = {
        "redis": await _probe("redis", _redis.ping()),
        "llm": await _probe("llm", _llm_health()) if "127.0.0.1" in config.LLM_BASE_URL or "localhost" in config.LLM_BASE_URL
        else {"ok": True, "skipped": "zewnętrzny dostawca"},
    }
    return {"status": "ok" if all(d["ok"] for d in deps.values()) else "degraded", "deps": deps}
