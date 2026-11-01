"""Eksporter metryk kolejki zadań (Redis Streams) dla Prometheusa — http://127.0.0.1:8063/metrics.

Uruchom obok workera:  python -m app.kolejka_metryki
Prometheus (kontener lgtm) scrapuje host.docker.internal:8063 co 5 s (grafana/prometheus.yaml, job `worker`).

Ćw. 14 — TODO: teraz eksportujemy tylko XLEN, a XLEN NIE jest długością kolejki — taskiq nie usuwa
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

import redis.asyncio as aioredis
from prometheus_client import Gauge, start_http_server

from . import config
from .zadania import GRUPA, STRUMIEN

PORT = int(os.environ.get("WORKER_METRICS_PORT", "8063"))
G_XLEN = Gauge("kolejka_xlen", "XLEN strumienia zadań (UWAGA: to nie jest długość kolejki)")


async def probkuj(r) -> dict:
    out = {"xlen": await r.xlen(STRUMIEN)}
    G_XLEN.set(out["xlen"])
    # TODO ćw. 14: lag, pending, wiek najstarszego nieodebranego (patrz docstring)
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
