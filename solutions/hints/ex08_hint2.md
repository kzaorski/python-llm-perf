# Ex. 08 — hint 2 (API)

- `limiter.pace(request_class, max_tokens)` — called before every call; it should wait until the requests
  bucket (RPM) and the output tokens bucket (OTPM; the provider reserves `max_tokens` at the start) allow it.
- `limiter.update_from_headers(status, headers)` — called after every response: synchronize the buckets with
  `*-limit`/`*-remaining`; on a 429, hold everyone until `retry-after`.
- Do not wait for a "probe": the slot pool holds back the first wave anyway. Evidence: the mock's
  `/admin/stats` (429 ≈ 0), `sum by (status) (increase(mock_llm_requests_total{provider="a"}[3m]))`.
