# Index of exercises and readings — python-llm-perf

The order is progressive — every exercise builds on the previous one (you can also assemble the application's
state "after ex. NN" with the script `scripts/overlay.py --after NN`). The theory readings (no tasks) come
before the blocks they cover. After each block there is a mini-incident: one flaw, diagnosed without reading
the code (`./incident.sh`).

## Skills map

After completing the course you can:
- read the trace of an LLM request: slot wait vs service vs TTFT; RED in Grafana (ex. 01)
- recognize the generator's closed model and coordinated omission; choose a k6 executor (ex. 02)
- derive capacity from Little's law and find the knee of the utilization → waiting curve (ex. 03)
- detect event loop blocking from the system's side: throughput, queue, p99 in open-model traffic (ex. 04)
- detect exhaustion of the anyio thread pool (40) — waiting without CPU (ex. 05)
- detect too few slots / too small a connection pool — slot wait, PoolTimeout (ex. 06)
- choose gunicorn's process model (sync vs UvicornWorker) and the number of processes (ex. 07)
- read the provider's limits (429, `anthropic-ratelimit-*`) and limit the rate on your side (ex. 08)
- recognize a retry storm (SDK × application, no jitter) and measure the amplification (ex. 09)
- set a timeout budget for second-long and multi-minute calls: read ≠ deadline, cancellation on disconnect,
  ping vs inactivity, k6/gunicorn timeouts (ex. 10)
- build a fallback with a circuit breaker (states, half-open) (ex. 11)
- introduce backpressure and load shedding; separate the pools of short and multi-minute calls (ex. 12)
- measure end-to-end TTFT and detect stream buffering that k6 does not see (ex. 13)
- observe a task queue (lag, age of the oldest) and tune the worker's concurrency (ex. 14)
- detect a cache stampede and fix it with single-flight (ex. 15)
- choose the batch window and size by measuring both ends (ex. 16)
- calibrate the capacity model on the real API (ex. 17, optional and paid)
- diagnose a complex incident with several flaws at once (ex. 18)

## Exercises

| # | File | Time | What you do |
|---|---|---|---|
| — | `exercises/00-theory.md` | ~60 min | **Reading:** queues, Little's law, the knee, open/closed model, RED/USE, LLMs and minute-long calls (read first) |
| — | `exercises/01a-queueing-theory-in-practice.md` | ~30 min | **Reading:** queueing theory in practice (before Block I) |
| 1 | `exercises/01-first-trace.md` | ~45 min | Start the stack, the first trace; the `llm.queue_wait` span, waiting in metrics |
| 2 | `exercises/02-open-vs-closed-model.md` | ~40 min | k6: open vs closed model, coordinated omission (F14) |
| 3 | `exercises/03-littles-law-capacity.md` | ~45 min + ~20 | Ramp, Little's law, the knee of the curve; **mini-incident I** |
| — | `exercises/04a-asyncio-loop-and-pools.md` | ~30 min | **Reading:** asyncio, the event loop and pools (before Block II) |
| 4 | `exercises/04-sync-client-in-async.md` | ~45 min | A synchronous client in `async def` — the system-level effect (F1) |
| 5 | `exercises/05-anyio-thread-pool.md` | ~30 min | The anyio thread pool of 40 (F2) |
| 6 | `exercises/06-slot-and-connection-pools.md` | ~45 min | Too few slots / connection pool, PoolTimeout (F3) |
| 7 | `exercises/07-gunicorn-process-model.md` | ~45 min + ~20 | gunicorn sync vs UvicornWorker (F13); **mini-incident II** |
| — | `exercises/08a-limits-retries-timeouts.md` | ~30 min | **Reading:** limits, retries, timeouts, fallback (before Block III) |
| 8 | `exercises/08-provider-limits.md` | ~45 min | 429, limit headers, rate limiter (F4) |
| 9 | `exercises/09-retry-storm.md` | ~40 min | Retry storm, jitter, budget (F5) |
| 10 | `exercises/10-timeouts-and-deadlines.md` | ~80 min | Timeouts, deadline, cancellation — multi-minute tests (F6, F16, F17) |
| 11 | `exercises/11-fallback-circuit-breaker.md` | ~40 min + ~20 | Fallback with a circuit breaker (F12); **mini-incident III** |
| — | `exercises/12a-backpressure-and-streaming.md` | ~30 min | **Reading:** backpressure, load shedding, streaming (before Block IV) |
| 12 | `exercises/12-backpressure-load-shedding.md` | ~90 min | Mixed traffic of seconds and minutes, 3-min inflow + drain (F7, F8, F18) |
| 13 | `exercises/13-streaming-ttft.md` | ~40 min + ~20 | Client-side TTFT, stream buffering (F9); **mini-incident IV** |
| — | `exercises/14a-task-queues-cache-batching.md` | ~25 min | **Reading:** task queues, cache, batching (before Block V) |
| 14 | `exercises/14-task-queue-worker.md` | ~50 min | taskiq: queue metrics, worker concurrency and prefetch (F15) |
| 15 | `exercises/15-cache-stampede.md` | ~30 min | Cache stampede, single-flight (F10) |
| 16 | `exercises/16-batching.md` | ~35 min | Batch window and size (F11) |
| 17 | `exercises/17-mock-vs-claude.md` | ~30 min | Mock vs real Claude (optional, ≈ $0.005; without a key `--mock-only`) |
| 18 | `exercises/18-final-incident.md` | ~90 min | **Final:** an incident with several flaws at once, diagnosis without code, report |

In total: the exercises with mini-incidents ~16 h, the readings ~3.5 h (the reading times are an estimate of
reading time). The longest exercises (10, 12, 18) contain real multi-minute tests — do not shorten them with the
second-long profile, which is only for a quick preview.

Concepts in a nutshell: `glossary.md`. Solutions and hints: the `solutions/` directory (`solutions/README.md`).
"Done" verification: `python check.py exNN` (or `python check.py --all`).
