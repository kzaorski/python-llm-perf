# Ćw. 03 — podpowiedź 2 (zapytania)

W Grafanie (okno 20 s = długość kroku rampy):
```
sum(rate(app_requests_total{endpoint="summary"}[20s]))
max(llm_inflight{klasa="krotkie"})
histogram_quantile(0.9, sum by (le) (rate(llm_queue_wait_seconds_bucket{klasa="krotkie"}[20s])))
```
Pojemność = sloty / W. Przy 4 slotach i W ≈ 1.05 s: ~3.8/s; przy 32: ~30/s.
