# Exercise 13: Streaming and TTFT — a stream the client receives at the end

> Time: ~40 min + mini-incident IV ~20 min

> Block IV. Reading `12a-backpressure-and-streaming.md` (TTFT, SSE, buffering, disconnect in a stream).

## Goal
The endpoint `POST /claims/{n}/reply/stream` answers the client with an SSE stream. The provider returns
the first token after ~0.5 s, the `llm_ttft_seconds` metric looks great — and yet the client waits for the
first character as long as the whole response takes. You measure TTFT **on the client side**, find where
the stream is buffered, and fix it. Along the way: why k6 does not see it.

## Theory in a nutshell
- **TTFT (time to first token)** — the time to the first chunk of the response. For a chat user it matters
  more than the total time: it decides whether "something is happening". Pitfall: TTFT measured at the
  provider (`llm_ttft_seconds`) ≠ TTFT at the client — along the way there can be a buffer, a proxy,
  compression.
- **Stream buffering** — the code collects chunks into a list and sends them at the end (or a
  proxy/middleware waits for the whole thing). The client gets a stream, but with a single event after
  everything is done. Symptom: client TTFT ≈ total time (100%).
- **A tooling pitfall: k6 and SSE.** `http_req_waiting` in k6 is the time to the response HEADERS.
  `StreamingResponse` sends the headers right away, so k6 shows a few ms regardless of buffering.
  Measure the first chunk: the application metric `app_stream_first_chunk_seconds` or a client that reads
  the stream (`scripts/stream_ttft.py`).
- **Disconnect in the middle of a stream** — Starlette (ASGI ≥ 2.4) will not stop the generator when the
  client disappears; you have to check `request.is_disconnected()` from time to time, otherwise the
  generation runs to the end (as in ex. 10).

## Steps
1. State after ex. 12, application on 8060. See the stream "with the naked eye" (`-N` turns off curl's
   buffer):
   ```bash
   curl -sN -X POST 127.0.0.1:8060/claims/7/reply/stream | head -c 300; echo
   ```
2. **Hypothesis:** the response has ~700 tokens (~3 s of generation). When will the client see the first
   `delta` event? What will k6 show in `http_req_waiting`?
3. Measurement from the client side and from the k6 side:
   ```bash
   python scripts/stream_ttft.py -n 20 -c 5
   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/stream.js -e RATE=2 -e DURATION=30s
   ```
   In my run: `stream_ttft.py` — 20 streams: client TTFT p50 **2.76 s** (max 3.81 s), total p50 2.76 s,
   **TTFT/total 100%**; k6: `http_req_waiting` p50 **3 ms** (headers), `client_total` p50 2.69 s.
4. Prometheus — the two TTFTs side by side:
   ```
   histogram_quantile(0.5, sum by (le) (rate(app_stream_first_chunk_seconds_bucket[2m])))
   histogram_quantile(0.5, sum by (le) (rate(llm_ttft_seconds_bucket{request_class="short"}[2m])))
   ```
   The first: when the application sent the client the first chunk. The second: when it received it from
   the provider.
5. Open **`app/stream.py`** (`TODO ex. 13`). Send every chunk right away (`yield sse("delta", …)` in the
   `async for` loop), call `first_chunk(timings, t0)` on the first chunk, and every ~20 chunks check
   `await request.is_disconnected()` and finish (`outcome = "cancelled"`).
6. Restart, repeat steps 3–4. In my run: `stream_ttft.py` — client TTFT p50 **0.49 s** (max 0.74 s), total
   p50 2.54 s, **TTFT/total 19%**; k6 `http_req_waiting` unchanged (2–3 ms) — k6 does not see the difference.
   (A query with a `[2m]` window right after the "before" run mixes the two — wait 2 min.)

   In my run (harness, 20 streams, 5 at a time): the first chunk at the client p50 **2.19 s = 100% of the
   total** → **0.55 s = 19%** of the total (2.89 s).
7. `python check.py ex13`

## Definition of done
- [ ] The first `delta` event reaches the client after < 30% of the whole response time.
- [ ] `app_stream_first_chunk_seconds` ≈ `llm_ttft_seconds` (the difference = the wait for a slot).
- [ ] You can explain why k6 did not detect the flaw and what to measure it with.
- [ ] `python check.py ex13` passes.

## Review questions
1. After the fix, `app_stream_first_chunk_seconds` is a bit larger than `llm_ttft_seconds`. What makes up the difference?
2. A reverse proxy that buffers responses sits between the application and the client. How will you detect it with the same tools?
3. The stream lasts 3 s, the client closed the tab after 0.5 s. What happens to the slot and the generation before and after the fix?

Answers: `solutions/questions_answers.md`.

## ★ Bonus (optional)
Add a first-chunk measurement to `k6/stream.js` using the `k6/experimental/streams` module, or by parsing
`r.body` with a timestamp from the server (the `end` event carries the timings). Can it be done without
changing the server?

---

## Mini-incident IV (after Block IV) — "summaries are slow while the analysis team is running"

> ~20 min. Diagnosis through `/diag`, `Server-Timing` and Prometheus; no code.

The claims adjusters complain: ordinary summaries take a second one time and get a 503 after a few seconds
the next — always when the analysis team submits a series of claim file analyses.

1. Stop your own application and start the incident:
   ```bash
   ./incident.sh start mini-IV
   ```
2. Reproduce it: 40 analyses of 60 s each in the background, and one summary after 3 s:
   ```bash
   for i in $(seq 40); do curl -s -o /dev/null -X POST -H 'x-mock-total-s: 60' -H 'x-mock-ttft-ms: 500' 127.0.0.1:8060/claims/$i/analysis & done
   sleep 3
   curl -s -o /dev/null -w 'short: %{http_code} after %{time_total} s\n' -X POST 127.0.0.1:8060/claims/1/summary
   curl -s 127.0.0.1:8060/diag | python -m json.tool | head -14
   ```
   In my run: `short: 503 after 5.0 s`; `/diag` → `queue.long`: **32 in flight + 8 waiting** (oldest 8.1 s),
   `queue.short`: 0 in flight; loop lag normal.
3. Answer without code: how many slots do the long calls occupy, how many does the short class have
   (`queue` in `/diag`, `llm_inflight` per class)? Do the queue limit and the wait budget work? What is
   missing?
4. Wait for the background analyses to finish (~1 min; `wait` in the same terminal) — otherwise the check
   will report "backlog from earlier traffic" instead of the actual diagnosis. Then `python check.py ex12`
   — FAIL on the incident (in my run: "short calls with 30 long ones: {200: 11, 503: 9}, wait p99 4.9 s —
   the long calls block the shared pool"). Finally `./incident.sh stop`.

Answer: `solutions/questions_answers.md`, the "Mini-incidents" section.

---
Stuck? `solutions/hints/ex13_hint1.md` → `hint2` → `hint3`. The ready-made solution:
`solutions/ex13_stream.py` → `app/stream.py`.
