# Ex. 13 — hint 2 (API / metrics)

- `app_stream_first_chunk_seconds` (sent to the client) vs `llm_ttft_seconds{request_class="short"}` (from the
  provider); `python scripts/stream_ttft.py -n 20 -c 5` — a client that reads the stream. k6 `http_req_waiting` =
  time to the headers, so it does not see the flaw.
- In `app/stream.py`: `yield sse("delta", …)` right away in the `async for` loop; `first_chunk(timings, t0)`
  on the first chunk; every ~20 chunks `await request.is_disconnected()` → finish with `outcome = "cancelled"`.
