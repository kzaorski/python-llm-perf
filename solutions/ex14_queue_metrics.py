"""[SOLUTION ex. 14 — copy to app/queue_metrics.py] Task queue metrics exporter (Redis Streams) for Prometheus — http://127.0.0.1:8063/metrics.

Run it next to the worker:  python -m app.queue_metrics
Prometheus (the lgtm container) scrapes host.docker.internal:8063 every 5 s (grafana/prometheus.yaml, job `worker`).

Ex. 14 ✅ (it used to be: only XLEN, and XLEN is NOT the queue length — taskiq does not delete
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
import time

import redis.asyncio as aioredis
from prometheus_client import Gauge, start_http_server

from . import config
from .tasks import GROUP, STREAM

PORT = int(os.environ.get("WORKER_METRICS_PORT", "8063"))
G_XLEN = Gauge("queue_xlen", "XLEN of the task stream (NOTE: this is not the queue length)")
G_LAG = Gauge("queue_lag", "Tasks not delivered to the consumer group (waiting)")
G_PENDING = Gauge("queue_pending", "Tasks delivered, unacknowledged (in progress + prefetch)")
G_AGE = Gauge("queue_oldest_age_seconds", "Age of the oldest undelivered task [s]")
G_AGE_PENDING = Gauge("queue_oldest_pending_age_seconds", "Age of the oldest delivered, unacknowledged task [s]")


def _age_s(entry_id: str) -> float:
    return max(0.0, time.time() - int(entry_id.split("-")[0]) / 1000.0)


async def sample(r) -> dict:
    out = {"xlen": await r.xlen(STREAM), "lag": 0, "pending": 0, "age_s": 0.0, "pending_age_s": 0.0}
    try:
        group = next(g for g in await r.xinfo_groups(STREAM) if g["name"] == GROUP)
    except (StopIteration, aioredis.ResponseError):
        group = None          # the stream/group does not exist yet (the worker has not started)
    if group is not None:
        out["lag"] = int(group.get("lag") or 0)
        out["pending"] = int(group.get("pending") or 0)
        next_entry = await r.xrange(STREAM, min="(" + group["last-delivered-id"], max="+", count=1)
        if next_entry:
            out["age_s"] = _age_s(next_entry[0][0])
        if out["pending"]:
            p = await r.xpending(STREAM, GROUP)
            if p.get("min"):
                out["pending_age_s"] = _age_s(p["min"])
    G_XLEN.set(out["xlen"])
    G_LAG.set(out["lag"])
    G_PENDING.set(out["pending"])
    G_AGE.set(out["age_s"])
    G_AGE_PENDING.set(out["pending_age_s"])
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
