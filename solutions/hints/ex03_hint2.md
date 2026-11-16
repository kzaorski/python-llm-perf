# Ex. 03 — hint 2 (queries)

In Grafana (a 20 s window = the length of a ramp step):
```
sum(rate(app_requests_total{endpoint="summary"}[20s]))
max(llm_inflight{request_class="short"})
histogram_quantile(0.9, sum by (le) (rate(llm_queue_wait_seconds_bucket{request_class="short"}[20s])))
```
Capacity = slots / W. With 4 slots and W ≈ 1.05 s: ~3.8/s; with 32: ~30/s.
