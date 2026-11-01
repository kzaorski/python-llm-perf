"""[ROZWIĄZANIE ćw. 14 — kopiuj do app/kolejka_metryki.py] Eksporter metryk kolejki zadań (Redis Streams) dla Prometheusa — http://127.0.0.1:8063/metrics.

Uruchom obok workera:  python -m app.kolejka_metryki
Prometheus (kontener lgtm) scrapuje host.docker.internal:8063 co 5 s (grafana/prometheus.yaml, job `worker`).

Ćw. 14 ✅ (było: tylko XLEN, a XLEN NIE jest długością kolejki — taskiq nie usuwa
przetworzonych wpisów, więc XLEN rośnie z każdym zleceniem i nigdy nie wraca do zera.
Dodaj metryki, które odpowiadają na pytania „ile czeka?" i „jak długo czeka najstarsze?":
- `kolejka_lag`               — wpisy jeszcze nieodebrane przez grupę konsumentów (XINFO GROUPS → lag),
- `kolejka_pending`           — odebrane, niepotwierdzone (w toku + prefetch) (XINFO GROUPS → pending),
- `kolejka_wiek_najstarszego_s` — wiek najstarszego NIEodebranego wpisu (ID wpisu = znacznik czasu ms;
                                pierwszy wpis po `last-delivered-id`: XRANGE strumień (last-delivered-id + COUNT 1).
"""
from __future__ import annotations

import asyncio
import os
import time

import redis.asyncio as aioredis
from prometheus_client import Gauge, start_http_server

from . import config
from .zadania import GRUPA, STRUMIEN

PORT = int(os.environ.get("WORKER_METRICS_PORT", "8063"))
G_XLEN = Gauge("kolejka_xlen", "XLEN strumienia zadań (UWAGA: to nie jest długość kolejki)")
G_LAG = Gauge("kolejka_lag", "Zadania nieodebrane przez grupę konsumentów (czekają)")
G_PENDING = Gauge("kolejka_pending", "Zadania odebrane, niepotwierdzone (w toku + prefetch)")
G_WIEK = Gauge("kolejka_wiek_najstarszego_s", "Wiek najstarszego nieodebranego zadania [s]")
G_WIEK_P = Gauge("kolejka_wiek_najstarszego_pending_s", "Wiek najstarszego odebranego, niepotwierdzonego [s]")


def _wiek_s(entry_id: str) -> float:
    return max(0.0, time.time() - int(entry_id.split("-")[0]) / 1000.0)


async def probkuj(r) -> dict:
    out = {"xlen": await r.xlen(STRUMIEN), "lag": 0, "pending": 0, "wiek_s": 0.0, "wiek_pending_s": 0.0}
    try:
        grupa = next(g for g in await r.xinfo_groups(STRUMIEN) if g["name"] == GRUPA)
    except (StopIteration, aioredis.ResponseError):
        grupa = None          # strumień/grupa jeszcze nie istnieją (worker nie wystartował)
    if grupa is not None:
        out["lag"] = int(grupa.get("lag") or 0)
        out["pending"] = int(grupa.get("pending") or 0)
        nast = await r.xrange(STRUMIEN, min="(" + grupa["last-delivered-id"], max="+", count=1)
        if nast:
            out["wiek_s"] = _wiek_s(nast[0][0])
        if out["pending"]:
            p = await r.xpending(STRUMIEN, GRUPA)
            if p.get("min"):
                out["wiek_pending_s"] = _wiek_s(p["min"])
    G_XLEN.set(out["xlen"])
    G_LAG.set(out["lag"])
    G_PENDING.set(out["pending"])
    G_WIEK.set(out["wiek_s"])
    G_WIEK_P.set(out["wiek_pending_s"])
    return out


async def main() -> None:
    start_http_server(PORT, addr="0.0.0.0")
    r = aioredis.from_url(config.REDIS_URL, decode_responses=True)
    print(f"metryki kolejki: http://127.0.0.1:{PORT}/metrics (strumień {STRUMIEN}, grupa {GRUPA})", flush=True)
    while True:
        try:
            await probkuj(r)
        except Exception as e:  # noqa: BLE001 — eksporter ma żyć mimo chwilowych błędów Redisa
            print("błąd próbkowania:", e, flush=True)
        await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
