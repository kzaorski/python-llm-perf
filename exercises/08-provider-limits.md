# Exercise 8: Provider limits — 429, `anthropic-ratelimit-*` headers and a limiter on our side

> Time: ~45 min (two runs of 60 s; the second drains the queue ~1 min after the end of inflow)

> Block III — The provider: limits, retries, timeouts, fallback (ex. 8–11). Read
> `08a-limits-retries-timeouts.md` first.

## Goal
You switch the mock to the `limits` profile (account limits like a real provider's: requests/min, input
tokens/min, output tokens/min) and send traffic above the limit. You count the 429s at the provider, read
the limit headers, and add a rate limiter that turns an avalanche of 429s into controlled waiting on our
side. You will also see what the limiter does NOT fix: throughput.

## Theory in a nutshell
- **LLM provider limits** — token buckets that refill continuously: RPM (requests/min), ITPM (input
  tokens/min), OTPM (output tokens/min; the provider reserves `max_tokens` at the start of the call).
  Exceeding any of them → `429 rate_limit_error` + `retry-after`. Pitfall: with short prompts and a large
  `max_tokens`, the bottleneck is OTPM, not RPM.
- **Headers** — every response carries `anthropic-ratelimit-{requests,input-tokens,output-tokens}-{limit,remaining,reset}`.
  Why: the client knows the limit and the bucket state before it gets a 429. Pitfall: a non-streaming
  response carries the headers only after the whole generation — do not wait for them before you send the
  first request.
- **A client-side limiter** — your own token bucket synchronized with the headers; before a call you wait
  for a token, and after a 429 you hold everyone until `retry-after`. Why: a 429 is a wasted connection and
  (with retries) a multiplication of traffic. Pitfall: the limiter does not increase capacity — the excess
  still waits, just on our side. Without a bound on that queue (ex. 12) the wait grows without limit.
- **Why were there no 429s with 4 slots?** The small slot pool was itself a concurrency limiter. After
  ex. 6 (32 slots) the application can finally overload the provider — the order of the exercises is not
  accidental.

## Steps
1. State after ex. 7, application on 8060 (32 slots). Mock profile:
   ```bash
   curl -s -X POST 127.0.0.1:8061/admin/profile/limits
   curl -s -D - -o /dev/null -H 'x-api-key: ***' -H 'anthropic-version: 2023-06-01' -H 'content-type: application/json' \
     -d '{"model":"claude-haiku-5-5","max_tokens":200,"messages":[{"role":"user","content":"test"}]}' \
     127.0.0.1:8061/v1/messages | grep -i ratelimit
   ```
   In my run: `requests-limit: 120`, `input-tokens-limit: 60000`, `output-tokens-limit: 12000`, and after one
   call `output-tokens-remaining: 11800` (the reserved `max_tokens` = 200), plus `*-reset`.
2. **Calculation and hypothesis.** A summary has `max_tokens=200`. How many summaries/min will the output
   token limit let through? And RPM? What happens with traffic of 3/s for 60 s (180 requests)? How many
   429s will the mock see, and how many errors will the client get?
3. Traffic:
   ```bash
   docker compose run --rm -e RESULT=ex08-before k6 run -o experimental-prometheus-rw /scripts/open_model.js -e RATE=3 -e DURATION=60s
   curl -s 127.0.0.1:8061/admin/stats | python -m json.tool | head -20
   ```
   In my run: k6 172 × 200 + **9 × 503**, p99 6.3 s; mock: 174 × 200 and **129 × 429**.
4. Prometheus — what the provider sees and what the application sees:
   ```
   sum by (status) (increase(mock_llm_requests_total{provider="a"}[3m]))
   sum by (status) (increase(llm_http_responses_total{provider="a"}[3m]))
   ```
   The client got fewer errors than the mock returned 429s — why? (Hint: who retries, ex. 9.)
5. Open **`app/llm/limiter.py`**: `pace()` and `update_from_headers()` (`TODO ex. 08`). Add:
   - two buckets: requests/min and output tokens/min (you reserve `max_tokens`), refilled continuously,
   - `update_from_headers()`: from `*-limit` and `*-remaining` you set the limit and correct the level
     downward; on `status == 429` you hold everyone until `retry-after`,
   - `pace()`: you wait (FIFO, `asyncio.Lock`) until both buckets have tokens and the pause has elapsed;
     until you know the limits (the first responses) — you do not throttle (the slot pool holds back the
     first wave).
6. Restart the application, run `curl -s -X POST 127.0.0.1:8061/admin/profile/limits` again (the profile
   also sets the limit buckets to full), and repeat step 3 with `-e RESULT=ex08-after`. In my run: mock
   **0 × 429** (167 × 200), k6 165 × 200 with no errors, but slot wait p90 36.5 / p99 **44.1 s** and a test
   of 106 s with a 60 s inflow; k6 skipped 16 iterations (`dropped_iterations` — the VUs were waiting in the
   limiter's queue; count them as excess).

   In my run (harness, 3/s × 60 s): **133 × 429** at the mock and 7 requests ending with
   `503 provider_rate_limited`, p99 6.7 s → **0 × 429**, 180/180 OK, but slot wait p99 **58.2 s** — the
   excess waits on our side.
7. Reset the mock: `curl -s -X POST 127.0.0.1:8061/admin/reset` and run `python check.py ex08`
   (check sets the `limits` profile itself and sends 90 requests at once).

## Definition of done
- [ ] With the `limits` profile the mock does not return 429 (≤ 1%), and all requests end with 200.
- [ ] You can calculate from the headers how many requests of a given type the limit lets through per minute.
- [ ] You understand why p99 is still long after the fix and what ex. 12 will do about it.
- [ ] `python check.py ex08` passes.

## Review questions
1. Why does the limiter reserve `max_tokens` instead of the actual number of response tokens?
2. Two application processes, each with its own bucket. What happens, and how do the `*-remaining` headers help?
3. Why hold EVERYONE after the first 429, and not just that one request?

Answers: `solutions/questions_answers.md`.

## ★ Bonus (optional)
Add a third bucket: input tokens/min (ITPM), with the number of tokens estimated from the prompt length.
Build traffic in which ITPM is the bottleneck (long claims, small `max_tokens`).

---
Stuck? `solutions/hints/ex08_hint1.md` → `hint2` → `hint3`. A ready solution:
`solutions/ex08_limiter.py` → `app/llm/limiter.py` (includes ex. 1 and 6).
