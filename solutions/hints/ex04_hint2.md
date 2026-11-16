# Ex. 04 — hint 2 (API / metric)

- Symptom: `app_event_loop_lag_seconds` (event loop lag), the `/diag/ping` time, `/classify` requests lined
  up one after another in Tempo; the wall-clock profile in Pyroscope confirms it: time in an `httpx`/`ssl`
  read on the loop thread.
- Fix: `pipeline.execute(request, LLMJob(request_class="short", endpoint="classify", max_tokens=16, prompt=…,
  headers=pipeline.mock_headers(request)))` — through the semaphore, retries, and the async client.
