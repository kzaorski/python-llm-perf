# Exercise 15: Response cache and cache stampede — 50 questions, 50 calls

> Time: ~30 min

> Block V. Reading `14a-task-queues-cache-batching.md` (cache, TTL, stampede, single-flight).

## Goal
Customers keep asking the same questions ("how long does claim settlement take"). The endpoint `GET /faq?q=…` keeps
answers in Redis with a TTL — and yet for a popular question the provider gets a wave of identical calls every time the
key expires. You measure the stampede by the number of LLM calls and fix it with single-flight.

## Theory in a nutshell
- **Cache-aside with a TTL** — check the cache; on a miss compute and store. Intuition: it works great when traffic is
  spread out in time. Why it matters: an LLM call costs seconds and money, a Redis read — milliseconds.
- **Cache stampede (thundering herd)** — when the key is missing (the first time or after expiry), each of N concurrent
  requests sees a "miss" and calls the LLM itself. With a call lasting a second and 5 questions/s the miss window is as
  wide as the call time — and the longer you wait for a slot, the wider the window (final, ex. 18).
- **Single-flight** — one call per key, the others wait for its result. Within a process: a dictionary
  key → `asyncio.Future`; across processes (several gunicorn workers): a lock `SET key:lock NX PX`
  in Redis, the rest poll the cache. The trap: a lock without an expiry time or a `Future` without exception handling —
  the death of the "owner" hangs everyone waiting.

## Steps
1. State after ex. 14, application on 8060. One question, twice:
   ```bash
   curl -s "127.0.0.1:8060/faq?q=how-long-does-settlement-take" | head -c 150; echo
   curl -s "127.0.0.1:8060/faq?q=how-long-does-settlement-take" | head -c 150; echo
   ```
   The `cache` field: `miss`, then `hit`.
2. **Hypothesis:** 50 clients ask about the same NEW question at the same time. How many LLM calls will the mock see?
3. Measurement — the number of 200 responses at the mock before and after (both "providers", because after ex. 11 traffic may go to `b`):
   ```bash
   Q="does-the-policy-cover-flooding-$RANDOM"
   A0=$(curl -s 127.0.0.1:8061/admin/stats | python -c 'import json,sys; d=json.load(sys.stdin); print(d["a"]["responses"].get("200",0)+d["b"]["responses"].get("200",0))')
   seq 50 | xargs -P 50 -I{} curl -s -o /dev/null -w '%{http_code}\n' "127.0.0.1:8060/faq?q=$Q" | sort | uniq -c
   A1=$(curl -s 127.0.0.1:8061/admin/stats | python -c 'import json,sys; d=json.load(sys.stdin); print(d["a"]["responses"].get("200",0)+d["b"]["responses"].get("200",0))')
   echo "LLM calls: $((A1 - A0))"
   ```
   Prometheus: `sum by (outcome) (app_cache_total)` — a counter since the process start (after a fresh restart
   `increase()` will not count the first series of samples, so look at the values here). In my run: the mock — **50 LLM
   calls**, 50 × 200 for the clients; `app_cache_total{outcome="miss"}` = 50.
4. In Tempo find a few `GET /faq` traces from the same moment: does each have its own `llm.call`?
5. **Single-flight (F10).** In **`app/cache.py`** (`TODO ex. 15`) in `get_or_compute()`:
   - after a miss check the dictionary `_inflight[k]`; if the key is there — `await asyncio.shield(fut)` and return `"shared"`;
   - otherwise create a `Future`, put it in the dictionary, acquire the lock `r.set(k + ":lock", "1", nx=True,
     px=…)`, compute, store, set the `Future` result (or the exception), and in `finally` remove the entry and the lock;
   - whoever did not get the lock (another process is computing) polls the cache every ~50 ms.
6. Restart, repeat step 3 with a new `Q`. In my run: 50 × 200, **1 LLM call**; `app_cache_total`:
   `miss` 1, `shared` 49.

   In my run: **50 LLM calls** (p99 4.6 s) → **1 call** (49 "shared"), p99 1.32 s.
7. `python check.py ex15`

## Definition of done
- [ ] 50 concurrent identical questions → 1 LLM call; `app_cache_total{outcome="shared"}` grows.
- [ ] An error in the "owner's" call does not hang the waiters (they get the same error, they do not wait forever).
- [ ] `python check.py ex15` passes.

## Review questions
1. After the fix p99 dropped from 4.6 s to 1.32 s, although the number of clients is the same. Where does the latency gain come from?
2. Why is a `Future` dictionary alone not enough with gunicorn and two processes (ex. 07)?
3. How will single-flight behave when the "owner's" call lasts longer than the TTL of the lock in Redis?

Answers: `solutions/questions_answers.md`.

## ★ Bonus (optional)
Add refresh-ahead (stale-while-revalidate): for the last 10% of the TTL return the stale value and recompute one copy
in the background. How does this change the `rate(llm_call_duration_seconds_count[1m])` chart under constant FAQ traffic?

---
Stuck? `solutions/hints/ex15_hint1.md` → `hint2` → `hint3`. The ready solution:
`solutions/ex15_cache.py` → `app/cache.py`.
