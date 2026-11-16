# Exercise 9: Retry storm — one request, nine attempts

> Time: ~40 min (two runs of 20 s + analysis)

> Block III. Reading `08a-limits-retries-timeouts.md` (retries, backoff, jitter, retry budget).

## Goal
The provider is overloaded (the `overload` profile: capacity of 8 generations, queue of 8, the excess gets
`529 overloaded`). The application retries errors quickly and without jitter — ON TOP of the retries the SDK
already does. You measure the amplification: how many HTTP attempts there are per client request, and
whether the retries save anything at all. You leave a single retry layer with backoff, jitter and a budget.

## Theory in a nutshell
- **Retry amplification** — layers multiply: SDK `max_retries=2` (3 attempts) × application 3 attempts
  = up to 9 HTTP attempts for a single request. Under overload every attempt adds traffic exactly where
  there is already too much. Pitfall: every layer looks reasonable on its own.
- **Exponential backoff with full jitter** — pause = random from [0, min(cap, base · 2^attempt)].
  Exponential gives the provider time, and jitter breaks synchronization: clients that got an error at the
  same moment do not come back in the same wave. A fixed pause of 100 ms = everyone comes back together.
- **`retry-after`** — 429 and 529 tell you when to come back. Honor it before your own backoff.
- **Retry budget** — retries ≤ a fraction (e.g. 20%) of the requests in the last window. In a mass outage
  you retry little instead of multiplying traffic ×3. Pitfall: without a budget, retries are "free" only
  when errors are rare.
- **Do not retry timeouts (at this level)** — a provider that did not answer in time is usually still
  working on the previous attempt; a repeat doubles its load and your wait (ex. 10).

## Steps
1. State after ex. 8, application on 8060. Mock profile:
   ```bash
   curl -s -X POST 127.0.0.1:8061/admin/profile/overload
   ```
2. Look at the client configuration: `curl -s 127.0.0.1:8060/diag | python -m json.tool` → `clients`:
   `max_retries` of the short client. How many attempts at most will a single request make, counting
   `app/llm/retries.py` too (3 attempts, 100 ms apart)?
3. **Hypothesis:** traffic of 10/s for 20 s (200 requests), the provider accepts 8 + 8 in the queue. How
   many HTTP attempts per request? How many 529s? Will the retries save most of the requests?
   ```bash
   docker compose run --rm -e RESULT=ex09-before k6 run -o experimental-prometheus-rw /scripts/open_model.js -e RATE=10 -e DURATION=20s
   ```
4. Calculate the amplification (the application counts EVERY HTTP attempt, including those inside the SDK):
   ```bash
   curl -s 127.0.0.1:8060/diag | python -c "import json,sys; d=json.load(sys.stdin); p=sum(x['n'] for x in d['http_attempts']); z=sum(x['n'] for x in d['outcomes'] if x['endpoint']=='summary'); print('HTTP attempts', p, 'requests', z, 'per request', round(p/max(z,1),2))"
   ```
   and in Prometheus (the same numbers over time):
   ```
   sum(increase(llm_http_attempts_total[2m])) / sum(increase(app_requests_total{endpoint="summary"}[2m]))
   sum by (status) (increase(llm_http_responses_total[2m]))
   ```
   In my run (exactly these commands): 172 × 200 + 29 × 502, p99 6.4 s; `/diag`: **622 HTTP attempts for 201
   requests = 3.09**; mock: 172 × 200 and 450 × 529. (The `/diag` counter runs from the start of the
   process — measure on a freshly started application.)
5. Fix two things:
   - **`app/llm/client.py`**: the short client without SDK retries (`max_retries=0`) — a single retry layer;
   - **`app/llm/retries.py`**: exponential backoff with full jitter (base 0.5 s, cap 8 s),
     `retry-after` takes precedence, a 20% retry budget in a 10 s window, no retrying of timeouts
     (`anthropic.APITimeoutError`, `httpx2.TimeoutException`). Remember: 529 is `anthropic.OverloadedError`
     — it is not a subclass of `InternalServerError`.
6. Restart the application, `curl -s -X POST 127.0.0.1:8061/admin/profile/overload`, and repeat steps 3–4
   with `-e RESULT=ex09-after`. In my run: 162 × 200 + 39 × 502, p99 3.6 s; `/diag`: **242 attempts for 201
   requests = 1.20**; mock 162 × 200 and 80 × 529. Note: a Prometheus query with a `[2m]` window right after
   the previous run mixes the two (mine showed 2.21) — wait 2 min or narrow the window to the test time
   (`[30s]`).

   In my run (harness, 10/s × 20 s): **3.65 HTTP attempts / request** (730 attempts, 567 × 529), 163 OK,
   p99 6.4 s → **1.20** (240 attempts, 88 × 529), 152 OK, p99 3.6 s. Almost the same number of successes —
   retries without backoff saved nothing; they only loaded the provider three times over.
7. `curl -s -X POST 127.0.0.1:8061/admin/reset` and `python check.py ex09`.

## Definition of done
- [ ] With the `overload` profile there are ≤ 1.5 HTTP attempts per request.
- [ ] A single retry layer (SDK `max_retries=0` for short requests), with jitter, `retry-after` and a budget.
- [ ] You can calculate the amplification from `/diag` and from Prometheus.
- [ ] `python check.py ex09` passes.

## Review questions
1. After the fix there are FEWER successes (152 vs 163). Why is this not a regression?
2. Why is full jitter (random from 0) better than "backoff ± 10%"?
3. Where should the only retry layer live — in the SDK or in the application? What argues for each option here?

Answers: `solutions/questions_answers.md`.

## ★ Bonus (optional)
The `unstable` profile (random 529/500 and mid-stream errors) at a traffic of 2/s: does the retry budget
block sensible retries at low traffic? How do you choose the minimum budget (`max(1, 20%)` in the solution)?

---
Stuck? `solutions/hints/ex09_hint1.md` → `hint2` → `hint3`. A ready solution:
`solutions/ex09_retries.py` → `app/llm/retries.py` and `solutions/ex09_client.py` → `app/llm/client.py`.
