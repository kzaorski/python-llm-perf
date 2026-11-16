# Ex. 02 — hint 2 (API)

The `constant-arrival-rate` executor: `rate` (how many iterations), `timeUnit` (`'1s'`), `duration`, `preAllocatedVUs`,
`maxVUs`. In this model VUs are just "workers" that do the sending — you need ≈ rate × the longest response time
(Little). Check `dropped_iterations` in the summary (and `k6_dropped_iterations_total` in
Prometheus) — it must be 0. The tag `model: 'open'` (already in the file) lets you compare series in Prometheus; `gracefulStop` > the longest request.
