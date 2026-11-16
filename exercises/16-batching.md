# Exercise 16: Batching — batch window and size vs latency and throughput

> Time: ~35 min

> Block V. Reading `14a-task-queues-cache-batching.md` (batching: window, size, the two ends).

## Goal
Assessing a claim's priority (`POST /claims/{n}/priority`) is a short task: a few output tokens. Instead of one call
per claim, the application collects requests into a batch and sends one call for many claims — fewer requests to
the provider (the RPM limit, ex. 08). The batch window and size, however, were chosen "by eye". You measure both ends:
a single request under low traffic and batches under high traffic, and you choose the parameters to fit the SLO.

## Theory in a nutshell
- **Batching** — the shared overhead (connection, system prompt, slot, RPM limit) divided by N claims.
  Intuition: a bus instead of taxis. Why it matters: fewer calls for the same traffic.
- **Window (`WINDOW_S`)** — how long we wait for the batch to fill. Under low traffic every request waits the
  full window — you add it directly to latency.
- **Size (`MAX_BATCH`)** — the upper bound on claims in one call. Too big: ~N× larger input, a longer
  generation (call time grows with the number of output tokens), one slow batch ruins the tail for all N; with an input-token
  limit (ITPM) a 429 hits the whole batch at once.
- The trap: you measure only under high traffic (full batches, "it works") or only single requests — you need both ends.
  Little: at λ requests/s a window T collects on average λ·T claims.

## Steps
1. State after ex. 15, application on 8060. Look into **`app/batch.py`**: `WINDOW_S = 2.0`, `MAX_BATCH = 100`.
2. **Hypothesis:** how long will a single priority request take when nobody else is asking? And 30 concurrent ones — how
   many batches, of what size?
3. Both ends:
   ```bash
   curl -s -w '  [%{time_total} s]\n' -X POST 127.0.0.1:8060/claims/7/priority
   seq 30 | xargs -P 30 -I{} curl -s -X POST 127.0.0.1:8060/claims/{}/priority | python -c "import sys,json; r=[json.loads(l) for l in sys.stdin.read().replace('}{','}\n{').splitlines() if l.strip()]; print('responses', len(r), 'batch sizes', sorted({x['batch_size'] for x in r}), 'wait max ms', max(x['batch_wait_ms'] for x in r))"
   ```
   Prometheus — the average batch size since the process start (the histogram is counted from the application start;
   `rate()`/`increase()` after a fresh restart will not count the first series of samples, and a quantile from a few
   batches is only a bucket interpolation):
   ```
   sum(app_batch_size_sum) / sum(app_batch_size_count)
   ```
   In my run: a single request **2.56 s** (`batch_wait_ms` 2001.6 — the whole window), 30 concurrent → one
   batch of **30**, wait max 2002 ms; average batch 15.5.
4. In Tempo open the trace of a single request: how much of the time is the batch wait, how much is `llm.call`?
5. **Choosing the parameters (F11).** In **`app/batch.py`** (`TODO ex. 16`) change `WINDOW_S` and `MAX_BATCH`. Criteria:
   a single request < 1.2 s (the window must not dominate latency), at ~20–30 requests/s a batch > 1 (otherwise
   batching gives nothing) and small (a short generation). Use Little's law to calculate how many claims a 50 ms window collects at 30/s.
6. Restart, repeat step 3. In my run: a single request **0.79 s** (batch wait 53 ms), 30 concurrent →
   batches of **14 and 16**, wait max 50 ms; `check.py ex16`: a single request 0.60 s, batch max 16.

   In my run (window 2 s / batch 100 → 50 ms / 16): a single request **2.78 s → 0.54 s**; open traffic 30/s × 10 s:
   batches ~60, 5 calls, p99 4.50 s → batches p50 2 / max 5, 146 calls, p99 1.14 s.
7. `python check.py ex16`

## Definition of done
- [ ] A single request < 1.2 s; with 30 concurrent a batch > 1 and ≤ 32.
- [ ] You can state the cost and the gain of your window: how many ms it adds, by how much it reduces the number of calls.
- [ ] `python check.py ex16` passes.

## Review questions
1. After the change the number of LLM calls rose from 5 to 146. Why is that a good result? When would it be a bad one?
2. The provider has an ITPM limit. What happens to a batch of 100 claims when 20% of the limit is left, and what happens to a batch of 5?
3. How do you choose the window when the priority SLO is p99 < 1 s and traffic varies during the day from 0.1/s to 50/s?

Answers: `solutions/questions_answers.md`.

## ★ Bonus (optional)
An adaptive window: send immediately if more than X ms have passed since the previous batch and nobody is waiting; collect
only while a call is in progress (a batch "from whatever accumulated in the meantime"). Compare both ends with the
fixed-window version.

---
Stuck? `solutions/hints/ex16_hint1.md` → `hint2` → `hint3`. The ready-made solution:
`solutions/ex16_batch.py` → `app/batch.py`.
