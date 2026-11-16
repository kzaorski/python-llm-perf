# Ex. 06 — hint 2 (metrics)

- `max_over_time(llm_inflight{request_class="short"}[2m])` pinned at 4; `llm_waiting` and
  `llm_oldest_waiting_age_seconds` grow; the `llm_queue_wait_seconds` histogram; `/diag` → `queue`.
- The other side: `max_over_time(mock_llm_generating{provider="a"}[2m])` — how many generations at once the
  provider sees. When the semaphore is large and the httpx2 pool small (`LLM_CONNECTIONS=8`), the mock sees
  ≤ 8, and the wait in the pool does NOT go into `llm.queue_wait` (and with a pool timeout it ends in
  `APITimeoutError` — PoolTimeout).
