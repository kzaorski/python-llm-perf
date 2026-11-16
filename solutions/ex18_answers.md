# Ex. 18 — answer key: the incident "everything slowed down on Monday morning"

> Read only after you have written your own report.

`./incident.sh start final` starts the app in the state after ex. 17 with four flaws restored: one configuration
flaw (`LLM_SLOTS=4`) and three in the code. In addition, `FAQ_TTL_S=30` (a shorter cache TTL — not a defect, it
only shortens the period after which the stampede repeats, so that it is visible in a 4-minute test).

Traffic (`./incident.sh traffic`, k6 `incident.js`, 240 s, open model): summaries 8/s, streamed replies 1/s, FAQ 5/s
(5 questions), analyses 6/min (the client gives up after 30 s). The numbers below: the same traffic on the incident
and on the reference state (`./incident.sh start custom 17`), signals from Prometheus in the run window,
`dropped_iterations` = 0 in both.

## Defects — symptom → evidence → cause → fix

### 1. Too few LLM slots (configuration `LLM_SLOTS=4`) — ex. 06
- **Symptom:** summaries are slow or return 503 after ~5 s; on the client side (k6) 1406 × 503 next to 1619 × 200.
- **Evidence:** `max(llm_inflight{request_class="short"})` = **4** (reference: 17); slot wait p50 **3.99 s** (cut
  off by the 5 s wait budget; reference 0.003 s); `sum by (outcome) (increase(app_requests_total{endpoint="summary"}[5m]))`
  → `rejected` **≈1586** (reference 0; k6 counted 1406 × 503 for summaries — `increase()` extrapolates at the window
  boundaries and counts all rejected short requests, so the numbers do not match, but the order of magnitude is the same). The
  provider is underloaded: `max(mock_llm_generating)` = 16, of which 12 are analyses (reference 19). Trace: a long
  `llm.queue_wait` next to a short `llm.call` (`{span.llm.queue.wait_ms > 100.0}`).
- **Cause:** L = λ·W = 8/s × ~1 s ≈ 8 + FAQ + stream ≫ 4 slots. The rejections are the correct reaction of a bounded
  queue (ex. 12) to a lack of capacity — not a backpressure defect.
- **Fix:** slots from Little's law (32 for short, ex. 06) — remove the `LLM_SLOTS` override. Proof: the
  `check.py ex06` probe.
- **Diagnostic pitfall:** the 503s tempt you to "raise the queue limit". What tells them apart is `llm_inflight`
  stuck at 4 while the provider has spare capacity (with correct slots the 503s would appear only when
  `mock_llm_generating` ≈ capacity).

### 2. The stream is buffered in full (F9) — ex. 13
- **Symptom:** streamed replies "appear all at once after a few seconds"; k6 `http_req_waiting` is low (headers
  arrive immediately) — the k6 report looks fine.
- **Evidence:** `histogram_quantile(0.5, sum by (le) (rate(app_stream_first_chunk_seconds_bucket[5m])))` = **8.07 s**
  vs `llm_ttft_seconds` p50 **0.63 s** (reference: 0.48 s vs 0.48 s). Part of the 8 s is slot wait (defect 1), but
  the gap first chunk ≫ provider TTFT + wait remains — `scripts/stream_ttft.py`: the first chunk ≈ 100% of the
  total time.
- **Cause:** the generator collects the chunks and sends them after the generation has finished.
- **Fix:** `yield` every chunk immediately + check for disconnect (ex. 13). Proof: the `check.py ex13` probe.

### 3. FAQ cache without single-flight — stampede (F10) — ex. 15
- **Symptom:** FAQ is slow every ~30 s, the provider receives waves of identical questions.
- **Evidence:** `sum by (outcome) (increase(app_cache_total[5m]))` → `miss` **290** with 5 questions and a 30 s TTL
  (≈ 5 × 240/30 = 40 expected); LLM calls for FAQ **295**; no `shared` (reference: 36 misses / 36 calls + 36
  "shared"). Targeted test: 50 identical new questions → 50 LLM calls.
- **Cause:** every miss calls the LLM itself; there is no "someone is already computing this key" mechanism.
- **Fix:** single-flight (an in-process `Future` + `SET NX PX` in Redis, ex. 15). Proof: the `check.py ex15` probe.

### 4. No cancellation after the client disconnects (F16) — ex. 10
- **Symptom:** after the traffic ends the system "keeps doing something for a long time"; the provider generates
  analyses that nobody is waiting for (the analysis client gives up after 30 s).
- **Evidence:** `sum by (phase) (increase(mock_llm_cancelled_total[10m]))` = **0** despite abandonments on the k6
  side (reference: 24); `max(llm_inflight{request_class="long"})` = **13** (reference 4); `mock_llm_generating`
  drops to 0 only **125 s** after the traffic ends (reference 32 s); `/admin/stats` → `generating` > 0,
  `oldest_inflight_s` keeps growing after the end.
- **Cause:** the call is not cancelled when the client disconnects — it holds an app slot and a provider slot until
  the generation ends (minutes).
- **Fix:** a `request.is_disconnected()` guard + cancelling the work, a deadline per class (ex. 10). Proof: the
  `check.py ex10` probe.

## Interactions between the defects (verified by measurement)
- **1 amplifies 3:** a longer slot wait lengthens the miss window — all FAQ requests that arrived before the first
  one finished also see a "miss". That is why 290 misses instead of ~40.
- **1 inflates the symptom of 2:** the first chunk of the stream includes the slot wait; that is why you compare it
  with `llm_ttft_seconds` and the wait, not with the "norm" from ex. 13.
- **4 takes slots from the long requests for a long time**, but not from the short ones — the pools are separate
  (ex. 12); if they were not, defect 4 would deepen defect 1.

## What you should have ruled out (and with what)
- Retry storm and provider limits: the increase in the mock's responses during the incident is only 200s (836 in my
  run) — zero 429/529, so there is nothing to retry (with 4 slots the provider is underloaded). You check:
  `curl -s 127.0.0.1:8061/admin/stats` and `sum by (status) (increase(llm_http_responses_total[5m]))`.
- Event loop blocking / thread pool: `/diag/ping` and `app_event_loop_lag_seconds` — in this incident they are not
  the source of the problem (check with a number; in my run I did not measure them separately, so I give no value
  here).
- An unbounded queue: the short queue is bounded (when the inflow ended 45 were waiting, the oldest 4.9 s — the
  budget is 5 s), and the fast 503s are a symptom of defect 1, not a lack of backpressure.
- `status 0` in k6: 96 short (reference 122) = Docker Desktop network `dial: i/o timeout` with hundreds of new
  connections (the app did not record them; they occur in both variants); 25 long = the intentional abandonments
  after 30 s.

## Self-assessment rubric
| Level | Criterion |
|---|---|
| ⭐ | ≥ 2 defects identified with the correct cause, but without numbers or with a generic signal ("p99 is high"). |
| ⭐⭐ | All 4 defects with a specific signal and a number; the fix identified at the level of the mechanism. |
| ⭐⭐⭐ | As above + at least 2 documented exclusions + one interaction (e.g. 1 → 3) explained and backed by a number; correct interpretation of the 503s (defect 1, not backpressure) and of `status 0` (Docker network). |
| ⭐⭐⭐⭐ | As above + a comparison with the reference-state run in one table and PromQL alerts (bonus) that fire on the incident and not on the reference. |
