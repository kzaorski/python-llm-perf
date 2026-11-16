# Exercise 1: The first trace — where a request waits and where it works

> Time: ~45 min (including ~15 min for the first stack startup)

> Block I — Measurement and queueing theory (ex. 1–3). Before you start, read `00-theory.md`
> (at least "Waiting vs service" and "How to read traces, metrics and profiles in this course").
> Block reading: `01a-queueing-theory-in-practice.md`.

## Goal
You start the "claims adjuster's assistant" application, look at the trace of a single claim
summary, and add the missing measurement: **the time a request waits for an LLM slot**. After the
exercise every trace shows waiting (span `llm.queue_wait`) and service (span `llm.call`) separately,
and Prometheus has a waiting-time histogram. Every later exercise builds on this measurement.

## Theory in a nutshell
- **Response time = waiting + service.** Service is the work done for the request (here: the LLM
  call); waiting is standing in a queue before that work (here: for a free semaphore slot). Intuition:
  a checkout line — the cashier serves you for 1 min, but you stand at the register for 10. Why it
  matters: under load almost all of the latency growth is waiting, not slower service. Pitfall: you
  cannot see waiting in a trace if nobody measured it — it looks like an "empty gap", or you add it to
  the service time.
  (→ `00-theory.md` "Waiting vs service")
- **Semaphore (slot)** — a counter of permits: at most N LLM calls at a time, the rest wait on
  `acquire()`. Why it matters: it protects the provider and our budget from a flood. Pitfall: a
  semaphore is a queue with no ticket window — it does not report how many people are waiting or for
  how long until you add that yourself.
- **Sibling span vs parent span** — waiting and the call happen one AFTER the other, so they are
  siblings under the request span. If `llm.queue_wait` were the parent of `llm.call`, the trace would
  say "the call was part of the waiting" — a falsehood that spoils every later analysis.
- **RED** (Rate, Errors, Duration) — three questions about every service: how many requests/s, how
  many errors, how long. In this course: `app_requests_total{endpoint,outcome}` and
  `app_request_duration_seconds`.
  (→ `00-theory.md` "RED and USE for this application")

## Steps
1. **Stack and environment** (once for the whole course):
   ```bash
   docker compose up -d --wait                       # lgtm, redis, mock-llm (project llmperf)
   python -m venv .venv && .venv/bin/pip install -r requirements.txt
   source .venv/bin/activate
   python scripts/generate_claims.py                 # data/claims.jsonl (20,000 claims)
   ```
2. **The application** (terminal T1; leave it running):
   ```bash
   uvicorn app.main:app --port 8060
   ```
   T2: `curl -s 127.0.0.1:8060/health` — `"status": "ok"`, the dependencies `redis` and `llm` (the mock) are OK.
3. One summary, with headers:
   ```bash
   curl -s -D - -X POST 127.0.0.1:8060/claims/42/summary | grep -iE 'server-timing|^\{'
   ```
   `Server-Timing` carries the times in ms: `wait`, `llm`, `total`. Right now `wait` is close to 0.
4. **Before you look at the trace:** how many spans do you expect in the trace of one summary, and how
   are they related (who is whose parent)? Where in it will the slot wait show up?
5. Grafana http://127.0.0.1:3060 (admin/admin) → **Explore → Tempo → TraceQL**:
   ```
   {resource.service.name="claims-assistant" && name="POST /claims/{n}/summary"}
   ```
   Open the newest trace. You will see the chain `POST /claims/{n}/summary` → `llm.call` →
   `anthropic.messages.create` (the SDK's native span) → `POST` (httpx2 HTTP client) + small `http send`
   spans. There is no waiting — with a single request there was none anyway.
6. **Hypothesis:** the application has 4 LLM slots, a summary takes ~1 s. What happens with 40
   requests at once? How long will the last one take? Will the trace show it?
   ```bash
   for i in $(seq 1 40); do curl -s -o /dev/null -X POST 127.0.0.1:8060/claims/$i/summary & done; wait
   ```
   In Tempo pick the trace with the longest duration: the request span lasts several seconds, and
   `llm.call` starts only at the very end. Before it — a hole. That is the wait on the semaphore,
   invisible.
7. Open **`app/llm/limiter.py`**, function `slot()`, the `TODO ex. 01` spot. Add three things:
   - a `llm.queue_wait` span from the moment `t0_ns` to now — created **without activating it** (a
     sibling of `llm.call`, not its parent) and ended right away,
   - a `llm.queue.wait_ms` attribute on the request span (`trace.get_current_span()`),
   - a data point in the `telemetry.H_QUEUE_WAIT` histogram with the `request_class` attribute (via
     `telemetry.record`).
8. Restart the application (Ctrl+C in T1, then `uvicorn …` again) and repeat the loop from step 6. In
   Tempo:
   ```
   {name="llm.queue_wait"}
   {span.llm.queue.wait_ms > 100.0}
   ```
   The second query returns requests that waited longer than 100 ms (the attribute is a float — TraceQL
   compares types, so `> 100` without `.0` returns nothing) — in the trace the hole is now a
   `llm.queue_wait` span, and next to it (not under it) sits `llm.call`. TraceQL search sees fresh
   traces with a delay (measured: ~10 s after the loop 0 results, after ~30 s 40) — if it is empty,
   wait and refresh.
9. **Explore → Prometheus** (RED + waiting; metrics are exported every 5 s — wait a moment):
   ```
   sum by (endpoint, outcome) (rate(app_requests_total[1m]))
   histogram_quantile(0.99, sum by (le, endpoint) (rate(app_request_duration_seconds_bucket[1m])))
   histogram_quantile(0.99, sum by (le, request_class) (rate(llm_queue_wait_seconds_bucket[1m])))
   ```
   Compare the p99 of the request time with the p99 of the wait: what share of the latency is the queue?
10. `python check.py ex01`

## Definition of done
- [ ] The summary trace contains a `llm.queue_wait` span as a **sibling** of `llm.call` and a
      `llm.queue.wait_ms` attribute on the request span.
- [ ] Prometheus has `llm_queue_wait_seconds_bucket{request_class="short"}`.
- [ ] After the 40-request loop you can say how much of the slowest request's time was waiting and how
      much was the LLM.
- [ ] `python check.py ex01` passes.

## Review questions
1. Why do you create the wait span with `start_span` (without activating it) rather than
   `start_as_current_span`? What would the trace show in the second case?
2. With 40 requests and 4 slots of ~1 s each: roughly how long did the last request wait? What does it
   follow from?
3. The `Server-Timing` header and the trace show the same breakdown. Why do you need both (who reads
   which)?

Answers: `solutions/questions_answers.md` (look AFTER your own attempt).

## ★ Bonus (optional)
Add to the `llm.queue_wait` span an attribute with the number of requests waiting at the moment of
entering the queue (`st.waiting_count`). Use TraceQL to find requests that found a queue longer than
20, and compare their wait with Little's law (ex. 3).

---
Stuck? Graded hints: `solutions/hints/ex01_hint1.md` (direction) →
`hint2` (OTel API) → `hint3` (pseudocode). The ready-made solution is the LAST rung:
`solutions/ex01_limiter.py` → `app/llm/limiter.py`.
