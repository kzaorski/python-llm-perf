# Ex. 16 — hint 2 (metrics)

- The response of `POST /claims/{n}/priority` carries `batch_size` and `batch_wait_ms`.
- Prometheus: `sum(app_batch_size_sum) / sum(app_batch_size_count)` — the average batch since the process start.
- Little: a window T at λ requests/s collects on average λ·T claims (30/s × 0.05 s ≈ 1.5; in a burst of 30 at once — more).
- The check's criteria: a single request < 1.2 s, with 30 parallel 1 < batch ≤ 32.
