"""Background task queue (taskiq + Redis Streams): summaries enqueued by POST /claims/{n}/summary/async.

Producer (the app): `await background_summary.kiq(n, headers, time.time())` → an entry in the Redis stream.
Worker:  taskiq worker app.tasks:broker --workers 2 --max-async-tasks 100     (taskiq defaults)
Result:  GET /jobs/{id} (a result backend in Redis, 1 h).

Ex. 14 (F15): the worker concurrency is not derived from anything. By default taskiq runs 2 processes × 100
tasks at once, and each process fetches up to 100 entries in advance (`xread_count`, prefetch). The provider has capacity
for a few to a dozen generations at once — the excess gets 529 overloaded, tasks end with an error or
retry in waves, and the prefetch hoards tasks in one process (the other one idles).
TODO ex. 14: pick --workers × --max-async-tasks for the provider's capacity/limit (L = λ·W) and limit the prefetch.
Queue metrics (lag, age of the oldest) — app/queue_metrics.py.
"""
from __future__ import annotations

import os
import time

from taskiq import TaskiqEvents, TaskiqState
from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker

from . import config, data, telemetry
from .llm import LLMJob, client, retries

STREAM = "llmperf:tasks"
GROUP = "llmperf-worker"
PREFETCH = int(os.environ.get("TASKS_PREFETCH", "100"))   # F15: the default xread_count of taskiq-redis

broker = RedisStreamBroker(config.REDIS_URL, queue_name=STREAM, consumer_group_name=GROUP,
                           xread_count=PREFETCH).with_result_backend(
    RedisAsyncResultBackend(config.REDIS_URL, result_ex_time=3600))

_C_COMPLETED = _H_DURATION = _H_WAIT = None


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def _start(state: TaskiqState) -> None:
    global _C_COMPLETED, _H_DURATION, _H_WAIT
    telemetry.configure(service="claims-worker", variant="worker")
    _C_COMPLETED = telemetry.meter.create_counter("tasks.completed", description="Tasks by outcome")
    _H_DURATION = telemetry.meter.create_histogram("tasks.duration", unit="s", description="Task execution time")
    _H_WAIT = telemetry.meter.create_histogram("tasks.wait", unit="s",
                                               description="Time from enqueueing to the task starting")


@broker.task(task_name="background_summary")
async def background_summary(n: int, headers: dict, enqueued_at: float) -> dict:
    start = time.time()
    telemetry.record(_H_WAIT, max(0.0, start - enqueued_at))
    z = LLMJob(request_class="short", endpoint="summary-job", max_tokens=200, headers=headers,
               prompt=f"Summarize the claim for the adjuster in 3 sentences.\n{data.describe_for_llm(data.claim(n))}")
    outcome = "ok"
    try:
        w = await retries.with_retries(lambda: client.complete(z))
        return {"claim": data.claim(n)["id"], "summary": w.text,
                "wait_s": round(start - enqueued_at, 3), "duration_s": round(time.time() - start, 3)}
    except Exception as e:
        outcome = type(e).__name__
        raise
    finally:
        telemetry.record(_C_COMPLETED, 1, outcome=outcome)
        telemetry.record(_H_DURATION, time.time() - start)
