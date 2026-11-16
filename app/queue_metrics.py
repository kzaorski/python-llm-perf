"""Task queue metrics exporter (Redis Streams) for Prometheus — http://127.0.0.1:8063/metrics.

Run it next to the worker:  python -m app.queue_metrics
Prometheus (the lgtm container) scrapes host.docker.internal:8063 every 5 s (grafana/prometheus.yaml, job `worker`).

Ex. 14 — TODO: for now we export only XLEN, and XLEN is NOT the queue length — taskiq does not delete
processed entries, so XLEN grows with every enqueued task and never returns to zero.
Add metrics that answer the questions "how many are waiting?" and "how long has the oldest been waiting?":
- `queue_lag`                   — entries not yet delivered to the consumer group (XINFO GROUPS → lag),
- `queue_pending`               — delivered, unacknowledged (in progress + prefetch) (XINFO GROUPS → pending),
- `queue_oldest_age_seconds`    — age of the oldest UNdelivered entry (the entry ID = a timestamp in ms;
                                  the first entry after `last-delivered-id`: XRANGE stream (last-delivered-id + COUNT 1).
"""
from __future__ import annotations

import asyncio
import os

import redis.asyncio as aioredis
from prometheus_client import Gauge, start_http_server

from . import config
from .tasks import GROUP, STREAM

PORT = int(os.environ.get("WORKER_METRICS_PORT", "8063"))
G_XLEN = Gauge("queue_xlen", "XLEN of the task stream (NOTE: this is not the queue length)")


async def sample(r) -> dict:
    out = {"xlen": await r.xlen(STREAM)}
    G_XLEN.set(out["xlen"])
    # TODO ex. 14: lag, pending, age of the oldest undelivered entry (see the docstring)
    return out


async def main() -> None:
    start_http_server(PORT, addr="0.0.0.0")
    r = aioredis.from_url(config.REDIS_URL, decode_responses=True)
    print(f"queue metrics: http://127.0.0.1:{PORT}/metrics (stream {STREAM}, group {GROUP})", flush=True)
    while True:
        try:
            await sample(r)
        except Exception as e:  # noqa: BLE001 — the exporter must survive brief Redis errors
            print("sampling error:", e, flush=True)
        await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
