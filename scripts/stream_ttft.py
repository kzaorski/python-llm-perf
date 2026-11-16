#!/usr/bin/env python3
"""TTFT as seen by the client of an SSE stream (ex. 13): the time to the first `delta` event vs the total time.

    python scripts/stream_ttft.py            # 10 requests, 5 at a time
    python scripts/stream_ttft.py -n 20 -c 10

k6 will not measure this: its http_req_waiting is the time to the headers, which StreamingResponse sends right away.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
import statistics
import time

import httpx2

APP = os.environ.get("APP_URL", "http://127.0.0.1:8060")


async def one(c: httpx2.AsyncClient, n: int) -> tuple[float | None, float]:
    t0 = time.perf_counter()
    first = None
    async with c.stream("POST", f"{APP}/claims/{n}/reply/stream", timeout=120) as r:
        async for chunk in r.aiter_bytes():
            if first is None and b"event: delta" in chunk:
                first = time.perf_counter() - t0
    return first, time.perf_counter() - t0


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=10)
    ap.add_argument("-c", type=int, default=5)
    a = ap.parse_args()
    results = []
    async with httpx2.AsyncClient() as c:
        for k in range(0, a.n, a.c):
            results += await asyncio.gather(*(one(c, random.randint(1, 20000)) for _ in range(min(a.c, a.n - k))))
    ttft = [x for x, _ in results if x is not None]
    total = [y for _, y in results]
    print(f"{len(results)} streams: client TTFT p50 {statistics.median(ttft):.2f} s (max {max(ttft):.2f} s), "
          f"total p50 {statistics.median(total):.2f} s, TTFT/total {statistics.median(ttft) / statistics.median(total):.0%}")


if __name__ == "__main__":
    asyncio.run(main())
