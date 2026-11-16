# Exercise 12: Backpressure and load shedding — mixed traffic: seconds and minutes in one application

> Time: ~90 min, including 2–3 multi-minute tests of 6.5–10 min each (180 s of inflow + draining)

> Block IV — Backpressure and streaming (ex. 12–13). First read `12a-backpressure-and-streaming.md`;
> `00-theory.md` "When the arrival rate exceeds capacity", "Multi-minute calls".

## Goal
Besides short summaries (one second), the application now handles claim file analyses (1–4 min). You
run realistic mixed traffic in the open model for 3 minutes and watch what happens during the run and
AFTER the inflow ends: short requests wait minutes behind long ones (head-of-line blocking in a shared
pool), the queue of long requests grows without a limit, clients give up, and the provider keeps
generating responses nobody is waiting for. You fix this with three mechanisms: separate pools per
class, a queue limit, and a wait budget (a fast 503 with `Retry-After`).

## Theory in a nutshell
- **Head-of-line blocking** — a shared queue/pool for tasks with wildly different service times: a few
  long ones hold the slots for minutes, and the short ones (which would take a second on their own)
  wait behind them. The median of the short ones ≫ their service time. Fix: separate pools (bulkhead) —
  each class has its own limit; the sum ≤ the provider's capacity.
- **Backpressure** — the system says "not now" instead of accepting everything. A queue without a limit
  is not a buffer, it is a promise with no backing: when the arrival rate > capacity, it grows without
  end, and the age of the oldest request exceeds the client's patience. (→ `12a`)
- **Load shedding** — two thresholds: a queue length limit (reject immediately) and a wait budget (whoever
  did not get a slot within X s gets a 503). A fast 503 with `Retry-After` in milliseconds is better
  than a 200 after 5 minutes that nobody is waiting for. Pitfall: in RED, rejections look like errors —
  but they are the correct response of an overloaded system; measure them separately
  (`outcome="rejected"`).
- **Backlog and drain** — after the inflow ends the system is still working. How many were waiting at the
  moment the inflow ended and how long the draining took tells you directly how long, after a peak,
  customers keep getting stale responses.
- **Capacity for long calls** — 16 slots at ~150 s per analysis ≈ 0.1 analyses/s. An arrival rate of
  0.4/s will NEVER fit — rejection is correct here, and ultimately long calls go to a task queue (ex. 14).

## Steps
1. State after ex. 11, application on 8060 (started normally). Look at **`k6/mixed.js`**: short
   `/summary` at 4/s, long `/analysis` at 0.4/s with a generation time of U[60, 240] s (a deterministic
   schedule, seeded), k6 timeout 400 s, `gracefulStop` 420 s — k6 does NOT abort in-flight requests after
   the inflow ends (the default 30 s would falsify the backlog and drain).
2. **Hypothesis (write down the numbers):** a shared pool of 32 slots, long calls arrive at 24 per
   minute × ~150 s on average. After how many seconds will the long calls occupy all the slots? How long
   will a short summary wait at t = 180 s? How long will draining take after the inflow ends?
3. **Run A (before the fix), ~9 min:**
   ```bash
   python scripts/measure.py ex12-mixed --inflow-s 180 -- run -q -o experimental-prometheus-rw /scripts/mixed.js -e DURATION=180s
   ```
   Watch during the run (Prometheus, "Last 15 minutes"):
   ```
   max by (request_class) (llm_waiting)
   max by (request_class) (llm_oldest_waiting_age_seconds)
   max by (request_class) (llm_inflight)
   sum by (request_class, outcome) (increase(app_requests_total[5m]))
   ```
   Note the moment `llm_inflight{request_class="long"}` reaches 32 — from then on the short requests are
   stuck. When it finishes: `results/ex12-mixed.json` (k6: times per class from `Server-Timing`) and
   `results/ex12-mixed-run.json` (`backlog_at_inflow_end`, `drain_after_inflow_end_s`, the mock's response
   deltas — `cancelled_*` are abandoned generations).
4. **Separate pools (F18).** In **`app/llm/limiter.py`** replace the single semaphore with a dictionary per
   class: short `SLOTS` (32), long `LLM_SLOTS_LONG` (16; from Little's law for the long class + the sum ≤
   the provider's capacity of 64). `semaphore(request_class)` returns the semaphore of the class.
5. **(Recommended) Run C — separate pools only, ~10 min.** Restart, the command from step 3. Are the short
   requests healthy now? What happens to the long ones and their queue? (If you are short on time, skip
   it — the numbers are in the table.)
6. **Backpressure (F7, F8).** In **`app/overload.py`** (`TODO ex. 12`):
   - `admit(request_class)`: when `MAX_WAITING[request_class]` requests are already waiting in the class
     queue (short 64, long 8) — `raise Rejected("queue_full", retry_after=…)` (the application turns it
     into a 503 + `Retry-After`);
   - `max_wait(request_class)`: the wait budget for a slot — short 5 s, long 20 s (`limiter.slot` raises
     `Rejected` once it is exceeded).
7. **Run B (after the fix), ~6.5 min:** restart and the command from step 3.

   In my run (794 requests: 721 short, 73 long; `dropped_iterations` = 0 in all of them):

   | Variant | Short: wait p50 / p99 | Short: total p99 | Long: result | Long: wait p50 / p99 | Backlog at t = 180 s | Drain |
   |---|---|---|---|---|---|---|
   | A — shared pool, queue without a limit | **29.0 / 131.2 s** | 132.3 s | 72 OK (1 aborted) | 32.2 / 130.9 s | short: **287 waiting**, oldest 71.6 s; long: 31 in flight + 28 waiting | **342 s** |
   | C — separate pools, no limit/budget | 0.0 / 0.0 s | 1.74 s | 43 OK, **30 abandoned by the client** (400 s) → 30 generations cancelled | **88.0 / 271.8 s** | long: 16 in flight + **46 waiting**, oldest 114.6 s | 402 s |
   | B — separate pools + queue limit + budget | 0.0 / 0.0 s | 1.76 s | 30 OK, **42 × fast 503** | 0.0 / 19.4 s | long: 16 in flight + 8 waiting (17 s) | **213 s** |

   A → C: separate pools remove the head-of-line blocking. C → B: the limit and the budget turn 30
   abandonments after minutes (wasted work) into 42 fast refusals with `Retry-After`; drain 402 → 213 s.
   (Run-to-run variance: when repeating the three runs I got drains of 342 / 402 / 235 s for A / C / B and a
   handful of `status 0` in k6 — the Docker network `dial: i/o timeout` from the README, not application
   responses. The ordering of the variants and the 30 OK + 42 × 503 split in B were the same in my repeat.)
8. **Quick preview (optional, does NOT replace the multi-minute run):** the same traffic shape at a
   shorter scale — useful when you only want to check that the code works:
   ```bash
   python scripts/measure.py ex12-preview --inflow-s 60 -- run -q /scripts/mixed.js -e DURATION=60s -e LONG_MIN_S=20 -e LONG_MAX_S=60
   ```
   In my run (state after ex. 12): ~2 min in total (60 s of inflow + 60.4 s of draining); short 238 × 200,
   wait p99 0 ms, total p99 1.71 s; long (20–60 s) 24 × 200, wait p99 1.05 s; 3 × `status 0` (Docker
   network, see the README). The preview confirms that the code works — only step 7 tells you about
   behavior under a multi-minute tail.
9. `python check.py ex12` (30 long calls of 15 s each + 20 short ones: the short ones wait < 1 s, the
   excess long calls get a fast 503; if `results/ex12-mixed.json` exists, the check appends the short
   calls' wait from your run).

## Definition of done
- [ ] In the mixed run the short requests do not wait for a slot (p99 ≈ 0), regardless of the long ones.
- [ ] The excess long calls get a fast 503 with `Retry-After`, not a response after minutes; the queue has a limit.
- [ ] From the `*-run.json` report you can read the backlog at the moment the inflow ended and the drain time.
- [ ] `python check.py ex12` passes.

## Review questions
1. After the fix, some clients get a 503. Why is that a better outcome than a 200 for everyone after 5 minutes?
2. How do you choose the wait budget for short requests (5 s)? What do you know about the client that the application does not?
3. The capacity for long calls (~0.1/s) < the arrival rate (0.4/s). What options do you have besides rejection? What will you choose in ex. 14?

Answers: `solutions/questions_answers.md`.

## ★ Bonus (optional)
Add priority: short requests may "borrow" free slots from the long pool when it is empty, but never the
other way around. Measure run B with this change — what happens to the drain?

---

Stuck? `solutions/hints/ex12_hint1.md` → `hint2` → `hint3`. The ready-made solution:
`solutions/ex12_limiter.py` → `app/llm/limiter.py` (includes ex. 1, 6, 8) and
`solutions/ex12_overload.py` → `app/overload.py`.
