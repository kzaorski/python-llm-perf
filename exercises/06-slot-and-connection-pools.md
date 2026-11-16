# Exercise 6: Too few slots, too small a connection pool — waiting for a resource you cannot see

> Time: ~45 min (three open-model runs of 15 s each; the first drains in ~1.5 min)

> Block II. Reading `04a-asyncio-loop-and-pools.md` (the semaphore, the httpx2 connection pool); `00-theory.md`
> "Little's law".

## Goal
The application has 4 LLM slots, and the target traffic is ~20 summaries/s. You measure the effects under
load (slot wait ≫ call time, an underloaded provider), choose the number of slots using Little's law, and
set it in the code. Then comes a second, sneakier variant: the semaphore is large, but the client's **HTTP
connection pool** is smaller — the wait moves to where your measurement cannot see it, and with a short
`pool timeout` it turns into errors.

## Theory in a nutshell
- **Too small a resource = a queue in front of it.** At λ = 20/s and W ≈ 1.06 s there should be L ≈ 21 calls
  in flight. With 4 slots the capacity is ~3.8/s — the excess of 16/s waits and the queue grows linearly
  during the inflow. Pitfall: the provider looks healthy and underloaded; the "slow LLM" is in fact our own
  queue.
- **The httpx2 connection pool** — the SDK's HTTP client keeps at most `max_connections` connections per
  provider. A call that did not get a connection waits in the pool until the `pool timeout`. SDK defaults:
  1000 connections and `pool=600 s`. Pitfall: with a pool smaller than the semaphore the wait happens INSIDE
  `llm.call` — it looks like a slow provider, while the `llm.queue_wait` span shows 0.
- **PoolTimeout** — after the `pool timeout` is exceeded httpx2 raises `PoolTimeout`, which the SDK wraps as
  `anthropic.APITimeoutError`. Pitfall: with fallback enabled (ex. 11) such a "timeout" quietly shifts
  traffic to the fallback provider — instead of an alarm you get unexpected cost and traffic at `b`.
- **Pool size = Little + headroom, not "more is better".** Slots beyond the provider's capacity/limits move
  the queue to the provider (429, 529 — ex. 8–9). The sum of slots across all processes ≤ the provider's
  capacity.

## Steps
1. State after ex. 5, application on 8060 (4 slots). The calculation from ex. 3: how many slots for 20/s?
2. **Hypothesis:** open-model traffic of 20/s for 15 s (300 requests). What will the p99 wait be? When will
   the last response arrive? How many generations at once will the mock see (`mock_llm_generating`)?
3. Traffic (your `k6/open_model.js` from ex. 2):
   ```bash
   docker compose run --rm -e RESULT=ex06-before k6 run -o experimental-prometheus-rw /scripts/open_model.js -e RATE=20 -e DURATION=15s
   ```
   During the run: `curl -s 127.0.0.1:8060/diag | python -m json.tool` — `queue.short.waiting` and
   `oldest_age_s` grow, `inflight` = 4. In my run: 277 × 200, test 74.3 s with a 15 s inflow, k6 skipped
   24 iterations (`dropped_iterations` — all 200 preallocated VUs were waiting and adding new ones could not
   keep up; with a system this clogged it is an underestimate of the queue anyway); wait p50 30.0 / p99
   **57.4 s** with LLM p50 1.04 s; `llm_waiting` max 213, `mock_llm_generating` max **4**.
4. Grafana → Prometheus (USE for the slots and for the provider):
   ```
   max_over_time(llm_inflight{request_class="short"}[2m])
   max_over_time(llm_waiting{request_class="short"}[2m])
   max_over_time(mock_llm_generating{provider="a"}[2m])
   histogram_quantile(0.99, sum by (le) (rate(llm_queue_wait_seconds_bucket{request_class="short"}[2m])))
   ```
   The slots are saturated (4), the queue is hundreds of requests long, and a provider with capacity 64
   generates 4 at a time.
5. Open **`app/llm/limiter.py`**: `SLOTS = int(os.environ.get("LLM_SLOTS", "4"))`. Set the default value
   from your calculation (L = λ·W + headroom for the tail; I took 32) and note in a comment where it came
   from.
6. Restart, repeat step 3 with `-e RESULT=ex06-after`. In my run: 301 × 200 in 16.2 s (18.6/s), wait p99
   **0 ms**, LLM p50 1.03 / p99 1.74 s.

   In my run (harness, the same 20/s × 15 s traffic): wait p50 32.3 / p99 **63.1 s** with LLM service p50
   1.06 s → after the change wait p99 **0.0 s**, overall p99 1.70 s.
7. **Variant: a connection pool smaller than the semaphore.** The `LLM_CONNECTIONS` variable sets
   `max_connections` of the httpx2 client (0 = the default 1000). **Hypothesis:** semaphore 64, pool 8 —
   where will the wait be, and will you see it in `llm.queue_wait`?
   ```bash
   LLM_SLOTS=64 LLM_CONNECTIONS=8 uvicorn app.main:app --port 8060
   docker compose run --rm -e RESULT=ex06-pool8 k6 run -o experimental-prometheus-rw /scripts/open_model.js -e RATE=20 -e DURATION=15s
   ```
   In my run: 294 × 200 + 6 × `status 0`, overall p50 13.1 / p99 25.4 s; "LLM" (the call together with the
   wait in the pool) p50 **8.5 s** instead of ~1 s; `llm_inflight` 64, `llm_waiting` max 116. Proof from the
   other side: `max_over_time(mock_llm_generating{provider="a"}[2m])` = 8 — the provider never received more
   than 8 calls, although the semaphore let 64 through (if the previous run ended < 2 min ago, narrow the
   window to the test time, for example `[40s]` — in my run `[2m]` still caught 21 from step 6).
   Do NOT derive the pool wait from the difference between spans — you simply are not measuring it.
8. You will see the same variant with a short `pool timeout` in practice after ex. 10 (the client has
   `pool=5 s` there). I measured it ahead of time: with `LLM_FALLBACK=0`, **86/300** requests end in a `504`
   (`APITimeoutError`, `PoolTimeout` underneath), and with fallback enabled the fallback provider `b` quietly
   served **77/300** requests. Write this down — you will come back to it in ex. 11.
9. Start the application normally (without the variables) and run `python check.py ex06`.

## Definition of done
- [ ] The default number of slots follows from the calculation (a comment in `limiter.py`), and 20/s traffic
      does not wait for a slot.
- [ ] You can show resource saturation with three series: `llm_inflight`, `llm_waiting`, `mock_llm_generating`.
- [ ] You understand why, with a connection pool of 8, the `llm.queue_wait` span lies, and how to detect it.
- [ ] `python check.py ex06` passes (20/s × 10 s: wait p99 < 0.5 s).

## Review questions
1. Traffic dropped to 2/s and you have 32 slots. Do you lose anything by keeping them? And with 320 slots?
2. Why is `pool timeout = 600 s` (the SDK default) worse for diagnosis than `5 s`?
3. You run 4 application processes of 32 slots each in front of a provider with capacity 64. What happens at
   full traffic?

Answers: `solutions/questions_answers.md`.

## ★ Bonus (optional)
Add `LLM_CONNECTIONS` to `/diag` (the `clients` section) and a Grafana panel "calls in flight vs connection
pool". What alert would you set to catch the variant from step 7 before customers see it?

---
Stuck? `solutions/hints/ex06_hint1.md` → `hint2` → `hint3`. The ready-made solution:
`solutions/ex06_limiter.py` → `app/llm/limiter.py` (it also contains ex. 1).
