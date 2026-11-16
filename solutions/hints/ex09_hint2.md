# Ex. 09 — hint 2 (API)

- A single layer: in `app/llm/client.py` the short client with `max_retries=0`; retries only in
  `app/llm/retries.py`.
- The pause: full jitter `random.uniform(0, min(LIMIT_S, BASE_S * 2**attempt))`; when there is a
  `retry-after`, it takes precedence.
- The budget: retries ≤ ~20% of requests in a 10 s window — in a mass outage you do not multiply traffic.
- What to retry: `RateLimitError`, `OverloadedError` (529 — it is NOT a subclass of `InternalServerError`!),
  `InternalServerError`, `APIConnectionError`; **not** timeouts (`APITimeoutError` ⊂ `APIConnectionError`).
