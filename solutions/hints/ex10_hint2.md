# Ex. 10 — hint 2 (API / metrics)

- `anthropic.Timeout(connect=3, read=15, write=10, pool=5)` for short; long: a stream, `read=60`,
  `max_retries=0` (the provider's ping every 15 s keeps the connection alive).
- Deadline: `async with asyncio.timeout(DEADLINE_S[request_class])` around the call → `DeadlineExceeded` (504).
- Disconnect: a guard task `while not await request.is_disconnected(): await asyncio.sleep(0.5)`;
  `asyncio.wait({work, guard}, return_when=FIRST_COMPLETED)`; when the guard finishes first — `work.cancel()`.
- Evidence: `sum by (phase) (increase(mock_llm_cancelled_total[10m]))`, `/admin/stats` (`generating`,
  `oldest_inflight_s`), `/diag` → `clients` (timeouts, `max_retries`). Start the application with `LLM_FALLBACK=0`.
