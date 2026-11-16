# Ex. 18 — hint 2 (where to look)

- Summaries: `max by (request_class) (llm_inflight)` vs `max(mock_llm_generating)`; slot wait p50; `rejected`
  outcomes. How many slots does the app have, and is the provider busy?
- Stream: `app_stream_first_chunk_seconds` vs `llm_ttft_seconds`; `python scripts/stream_ttft.py -n 20 -c 5`.
- FAQ: `sum by (outcome) (increase(app_cache_total[5m]))` — how many misses for 5 questions with a 30 s TTL?
- Analyses: `sum by (phase) (increase(mock_llm_cancelled_total[10m]))` and `mock_llm_generating` AFTER the traffic
  ends.
- Exclusions: HTTP attempts per request (`llm_http_attempts_total`), 429/529 at the mock, event loop lag.
