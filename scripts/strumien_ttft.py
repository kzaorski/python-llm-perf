#!/usr/bin/env python3
"""TTFT widziany przez klienta strumienia SSE (ćw. 13): czas do pierwszego zdarzenia `delta` vs czas całości.

    python scripts/strumien_ttft.py            # 10 żądań, po 5 naraz
    python scripts/strumien_ttft.py -n 20 -c 10

k6 tego nie zmierzy: jego http_req_waiting to czas do nagłówków, które StreamingResponse wysyła od razu.
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


async def jedno(c: httpx2.AsyncClient, n: int) -> tuple[float | None, float]:
    t0 = time.perf_counter()
    pierwszy = None
    async with c.stream("POST", f"{APP}/claims/{n}/reply/stream", timeout=120) as r:
        async for kawalek in r.aiter_bytes():
            if pierwszy is None and b"event: delta" in kawalek:
                pierwszy = time.perf_counter() - t0
    return pierwszy, time.perf_counter() - t0


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=10)
    ap.add_argument("-c", type=int, default=5)
    a = ap.parse_args()
    wyniki = []
    async with httpx2.AsyncClient() as c:
        for k in range(0, a.n, a.c):
            wyniki += await asyncio.gather(*(jedno(c, random.randint(1, 20000)) for _ in range(min(a.c, a.n - k))))
    ttft = [x for x, _ in wyniki if x is not None]
    cal = [y for _, y in wyniki]
    print(f"{len(wyniki)} strumieni: TTFT klienta p50 {statistics.median(ttft):.2f} s (max {max(ttft):.2f} s), "
          f"całość p50 {statistics.median(cal):.2f} s, TTFT/całość {statistics.median(ttft) / statistics.median(cal):.0%}")


if __name__ == "__main__":
    asyncio.run(main())
