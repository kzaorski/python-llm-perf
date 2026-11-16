# Exercise 11: A fallback provider with a circuit breaker

> Time: ~40 min (two runs of 40 s + draining) + mini-incident III ~20 min

> Block III. Reading `08a-limits-retries-timeouts.md` (fallback, circuit breaker, the closed/open/half-open states).

## Goal
The application has a fallback provider `b` (in the mock: separate limits and capacity, path
`/b/v1/messages`). When `a` hangs, EVERY request first pays the full timeout at `a` and only then goes to
`b`. You measure that cost under load and add a circuit breaker: after a few failures we stop asking `a`
for a while, then we check on it with a single probe request.

## Theory in a nutshell
- **A fallback without memory** — "try `a`, and if that fails, `b`". With a lasting failure of `a`, the time
  of every request = the timeout of `a` + the time of `b`, and the slots are tied up waiting for `a`.
  Pitfall: in the success metrics everything "works", only p50 jumps by the timeout.
- **A circuit breaker** — three states: **closed** (traffic to `a`, we count consecutive failures) → after
  N failures **open** (for T seconds straight to `b`, giving `a` time to get back on its feet) → after T
  **half-open** (one probe request to `a`; success closes, failure opens again). Why: an outage costs N
  timeouts, not all of them. Pitfall: requests that are already waiting for `a` will pay the timeout anyway.
- **What counts as a failure?** A hang, a connection error, a 5xx — yes. **429 and 529 — no**: they mean
  "too much traffic", and moving it to `b` carries the storm over to the backup provider.
  `APITimeoutError` is a subclass of `APIConnectionError` (`except APIConnectionError` catches it), and
  `OverloadedError` (529) is not a subclass of `InternalServerError`.
- **State visibility** — the breaker state as a span attribute (`llm.cb.state`) and a transition counter in
  `/diag`. Without them, "why is traffic going to b?" is a puzzle.

## Steps
1. State after ex. 10, application on 8060 started **normally** (fallback on, `LLM_FALLBACK=1` is the
   default). After ex. 10 the short client has `read=15 s`.
2. A failure of `a`: the provider is silent for 30 s before the first token (longer than our read timeout):
   ```bash
   curl -s -X PATCH '127.0.0.1:8061/admin/config?provider=a' -H 'content-type: application/json' \
     -d '{"ttft_median_ms": 30000, "ttft_sigma": 0}'
   ```
3. **Hypothesis:** traffic of 2/s for 40 s. What will the median response time be? How many of the 80
   requests will go to `a`?
   ```bash
   docker compose run --rm -e RESULT=ex11-before k6 run -o experimental-prometheus-rw /scripts/open_model.js -e RATE=2 -e DURATION=40s
   curl -s 127.0.0.1:8061/admin/stats | python -m json.tool | head -30
   ```
   In my run: 71 × 200 (all from `b`), p50 **16.1 s** (15 s read timeout of `a` + the call to `b`); mock: `a` —
   **71 × `cancelled_generating`** (every request first waited on `a`), `b` — 71 × 200. Prometheus:
   `sum by (provider) (increase(mock_llm_requests_total[2m]))` counts only completed responses (`a` = 0,
   `b` ≈ 74), so you will see the attempts to `a` in
   `sum by (provider) (increase(mock_llm_cancelled_total[2m]))`.
4. Open **`app/llm/fallback.py`** (`TODO ex. 11`). Add a breaker class (state, a consecutive failure
   counter, the opening time, a "probe in flight" flag) and use it in `invoke()`: ask `a` only when the
   breaker allows it; success → close; failure (`_is_outage(e)`) → count it; any other error → let it
   propagate. Set the `llm.cb.state` attribute on the current span and write the state transitions to
   `state.OUTCOMES` (`("cb", "a", "closed->open")`) — you will see them in `/diag`. Thresholds: 5 failures,
   30 s open.
5. Restart the application, run the `PATCH` from step 2 again, and repeat step 3 with `-e RESULT=ex11-after`.
   In my run: 73 × 200, p50 **1.31 s** (p90 16.1 s — only requests from before the breaker opened); **28**
   went to `a` (aborted), and `/diag` shows one `closed->open` transition; `check.py ex11`: median 1.05 s,
   to `a` 1/80. In `/diag` → `outcomes` look for entries with `endpoint: "cb"`. In Tempo:
   ```
   {span.llm.cb.state="open"}
   ```
   In my run (harness, the same scenario): p50 **19.8 s**, to `a` **80/80** → p50 **7.7 s**, to `a` **33/80**.
   The fix has a limit: ~30 requests were already in flight to `a` before the breaker opened — they paid
   the full 15 s (p90 22 s).
6. `curl -s -X POST 127.0.0.1:8061/admin/reset` and `python check.py ex11`.

## Definition of done
- [ ] With `a` hung, the median response time drops below 12 s, and < 60% of requests go to `a`.
- [ ] 429/529 do NOT switch traffic to `b` (check `_is_outage`).
- [ ] The breaker state is visible in the trace (`llm.cb.state`) and in `/diag`.
- [ ] `python check.py ex11` passes.

## Review questions
1. Why must a 529 neither open the breaker nor trigger the fallback?
2. What would happen if, in the half-open state, all requests were let through to `a` instead of one?
3. Go back to ex. 6, step 8: how does the breaker change the effects of a `PoolTimeout` with the fallback on?

Answers: `solutions/questions_answers.md`.

## ★ Bonus (optional)
Add a breaker state gauge (0/1/2) to the metrics and a panel in Grafana next to `mock_llm_requests_total`
per provider. Set `CB_OPEN_S=5` and watch the half-open probes every 5 s during an outage.

---

## Mini-incident III (after Block III) — "the provider says overload; we say our traffic is low"

> ~20 min. Diagnosis through `/diag`, Prometheus and the mock's `/admin/stats`; no code.

The provider sent a report: during peak hours your application sends it several times more requests than
you have users, and in waves. Your traffic is ~10 summaries/s.

1. Stop your own application and start the incident (it also sets the mock's `overload` profile):
   ```bash
   ./incident.sh start mini-III
   docker compose run --rm -e RESULT=mini-III k6 run -o experimental-prometheus-rw /scripts/open_model.js -e RATE=10 -e DURATION=20s
   ```
2. Calculate the amplification (the command from ex. 9, step 4) and check the statuses at the provider:
   ```bash
   curl -s 127.0.0.1:8061/admin/stats | python -m json.tool | head -20
   ```
   Prometheus: `sum(increase(llm_http_attempts_total[2m])) / sum(increase(app_requests_total{endpoint="summary"}[2m]))`.
   In my run: k6 177 × 200 + 24 × 502, p99 6.3 s; `/diag`: **625 HTTP attempts for 201 requests = 3.11**;
   mock 177 × 200 and **448 × 529**; `/diag` → `clients.short`: `max_retries` 2, read 600 s. `check.py ex09`:
   FAIL "×2.40 (529: 143)".
3. Answer without code: how many HTTP attempts per request? How many of them are 529s? Which layer retries
   (check `/diag` → `clients`), and do the retries save anything?
4. `python check.py ex09` — FAIL on the incident. Then `./incident.sh stop`.

Answer: `solutions/questions_answers.md`, the "Mini-incidents" section.

---
Stuck? `solutions/hints/ex11_hint1.md` → `hint2` → `hint3`. The ready-made solution:
`solutions/ex11_fallback.py` → `app/llm/fallback.py`.
