"""[SOLUTION ex. 16 — copy to app/batch.py] Claim priority assessment in batches (batching) — endpoint POST /claims/{n}/priority.

We collect single priority requests into a batch and send ONE LLM call for many claims:
fewer requests to the provider (the RPM limit), shared overhead. The price is waiting for the batch to fill up.

Ex. 16 (F11): a 2 s window and a batch of up to 100 claims — with low traffic every request waits the full window
(+2 s of latency), and with high traffic one call carries 100 claims (input ~100× larger, a long
generation; with a token limit — a 429 for the whole batch at once).
✅ ex. 16: a 50 ms window, batch ≤ 16 (measured: see the exercise).
"""
from __future__ import annotations

import asyncio
import os
import time

from fastapi import APIRouter

from . import data, pipeline, telemetry
from .llm import LLMJob

router = APIRouter()

# ex. 16 (F11) ✅: a window of milliseconds and a small batch. At ~20 requests/s a 50 ms window collects ~1–16
# claims (a reduction in calls of several to a dozen times), and adds ≤ 50 ms instead of 2 s. A batch ≤ 16 keeps
# the input (~16 × 80 tokens) and the generation (~16 × 6 tokens) short: one slow batch does not spoil the tail.
WINDOW_S = float(os.environ.get("BATCH_WINDOW_S", "0.05"))
MAX_BATCH = int(os.environ.get("BATCH_MAX", "16"))
LEVELS = ("high", "medium", "low")


class Batch:
    def __init__(self, window_s: float, max_size: int):
        self.window_s = window_s
        self.max = max_size
        self._pending: list[tuple[int, asyncio.Future, float]] = []
        self._timer: asyncio.TimerHandle | None = None

    async def prioritize(self, n: int) -> dict:
        fut = asyncio.get_running_loop().create_future()
        self._pending.append((n, fut, time.perf_counter()))
        if len(self._pending) >= self.max:
            self._flush()
        elif self._timer is None:
            self._timer = asyncio.get_running_loop().call_later(self.window_s, self._flush)
        return await fut

    def _flush(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        batch, self._pending = self._pending, []
        if batch:
            asyncio.ensure_future(self._run(batch))

    async def _run(self, batch: list) -> None:
        t_sent = time.perf_counter()
        telemetry.record(telemetry.H_BATCH, len(batch))
        descriptions = "\n\n".join(f"[{i + 1}] {data.describe_for_llm(data.claim(n))}" for i, (n, _, _) in enumerate(batch))
        z = LLMJob(request_class="short", endpoint="priority-batch", max_tokens=8 * len(batch) + 16,
                   prompt=f"Rate the priority (high/medium/low) of each claim:\n{descriptions}")
        try:
            w = await pipeline.execute(None, z)
        except Exception as e:  # noqa: BLE001 — the error of the whole batch goes to every waiting request
            for _, fut, _ in batch:
                if not fut.done():
                    fut.set_exception(e)
            return
        for i, (n, fut, t_in) in enumerate(batch):
            if not fut.done():
                fut.set_result({"claim": data.claim(n)["id"],
                                "priority": LEVELS[(len(w.text) + n + i) % 3],
                                "batch_size": len(batch),
                                "batch_wait_ms": round((t_sent - t_in) * 1000, 1)})


BATCH = Batch(WINDOW_S, MAX_BATCH)


@router.post("/claims/{n}/priority")
async def priority(n: int):
    return await BATCH.prioritize(n)
