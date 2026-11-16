# Ex. 15 — hint 2 (API)

- Within a process: `_inflight: dict[str, asyncio.Future]`; the first request creates `loop.create_future()`, the rest
  `await asyncio.shield(fut)` (shield: cancelling one waiter does not cancel the shared result).
- Across processes: `await r.set(k + ":lock", "1", nx=True, px=30_000)` — whoever did not get it polls `r.get(k)`
  every 50 ms.
- Counter: `telemetry.record(telemetry.C_CACHE, 1, outcome="shared")`; the query
  `sum by (outcome) (app_cache_total)` (a counter since the process start — after a fresh restart `increase()` loses the first series).
- The owner's error: `fut.set_exception(e)` — otherwise the waiters hang.
