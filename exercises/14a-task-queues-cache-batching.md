# 14a. Reading: task queues, cache and batching

A reading, not an exercise — no tasks and no definition of done. The goal is to understand three
techniques that **change the shape of the traffic** going to the LLM provider, before you see their
flaws in Block V: a task queue (moves work in time), a cache (removes part of the work) and batching
(glues work into bigger portions). Each one has its own calculation in terms of L = λW, and each one
can hide a problem instead of solving it. Every concept follows the same pattern:

> **Definition** → **Intuition/analogy** → **Why it matters** → **Common mistake**

Come back here when things stop adding up. Short definitions are in `glossary.md`.

---

## Task queue: producer, broker, worker

**Definition.** A **task queue** separates accepting work from doing it. The **producer** (the
application) writes a task to the **broker** and immediately answers the client with an identifier; a
**worker** (a separate process) picks tasks up and runs them at its own pace; the result goes to a
**result backend**, from which the client collects it. In the course: **taskiq** + **Redis Streams** —
the endpoint `POST /claims/{n}/summary/async` enqueues a summary, `GET /jobs/{id}` returns the result
(kept for 1 h); you start the worker with
`taskiq worker app.tasks:broker --workers 2 --max-async-tasks 4`.

A Redis stream is a log of entries (`XADD` appends), from which a **consumer group** reads the entries
that are new to the group (`XREADGROUP`) and acknowledges completion (`XACK`). taskiq tasks are
`async def` — the worker is an asyncio loop, just like the application, so the same concepts describe
its concurrency: slots, Little's law, the provider limit.

**Intuition.** A laundromat: you drop off a bag at the counter and get a ticket (producer → broker →
identifier). The machines (workers) wash at their own pace; you come back with the ticket for the
laundry (result backend). The queue of bags is visible in the back room — if someone counts it.

**Why it matters.** A task queue is the natural place for **multi-minute** calls and for traffic that
exceeds capacity only briefly: the client does not hold an HTTP connection for minutes, the application
does not hold a slot, and the excess waits in the broker instead of in process memory. You calculate
worker capacity from Little's law: **L = workers × max-async-tasks**, throughput X = L / W. The
measurement from the course: 2 × 4 = 8 parallel tasks, 200 tasks in 28.7 s → X ≈ 7.0/s →
W ≈ 8 / 7.0 ≈ 1.15 s per task.

**Common mistake.** "A task queue solves the capacity problem." It does not: when λ > X persists, the
backlog in the broker grows without bound, exactly as it grew in application memory. What you gain is
**visibility and durability** of the backlog and its separation from HTTP requests — not extra
capacity. You need queue metrics (below) and a decision about what to do when the backlog is too big.

---

## Worker concurrency vs the provider limit

**Definition.** The concurrency of a taskiq worker is the product of **`--workers`** (processes) ×
**`--max-async-tasks`** (tasks at a time in one process). It is a **closed** pool — exactly like the
closed model of a load generator: the worker will not fetch a new task until it finishes one of the
current ones (unless there is prefetch — see below).

**Intuition.** The number of washing machines. Ten machines on a single water connection that can
supply only four do not wash faster — the machines stop with an error.

**Why it matters.** By default taskiq runs **2 processes × 100** tasks at a time. In the `overload`
profile the provider has a capacity of 8 generations plus a queue of 8; above that — 529. Ex. 14, 200
tasks: with 2 × 100, **179 / 200 end with an error** within 6 s (220 × 529); with **2 × 4 = 8** (the
provider's capacity) — 200 / 200 in 28.7 s, 0 × 529. You choose worker concurrency to match the
capacity of what sits behind it, not the length of the queue in front of it.

**Common mistake.** "The queue is growing, let's add concurrency." If the provider is the bottleneck,
more concurrency turns a backlog in the queue (harmless, visible) into errors and retries (dangerous,
traffic-multiplying).

---

## Queue metrics: lag ≠ XLEN, pending, age of the oldest

**Definition.** For Redis Streams with a consumer group:
- **`XLEN`** — the number of entries in the stream. taskiq does **not** delete entries after they are
  processed, so XLEN grows with every task and is **not** the queue length (in the test from building
  the course: XLEN = 120 after all 120 tasks had been processed);
- **lag** (`XINFO GROUPS`) — the number of entries not yet **delivered** to the group — the real queue
  length;
- **pending** (`XPENDING`) — entries **delivered but not acknowledged**: in progress plus prefetched;
- **age of the oldest** — how long the oldest undelivered task has been waiting (a Redis Streams entry
  ID contains a timestamp in milliseconds, so the age is computed from the ID of the first entry after
  the group's `last-delivered-id`).

The course exporter (port 8063) exposes them as `queue_xlen` (deliberately — as a trap), `queue_lag`,
`queue_pending`, `queue_oldest_age_seconds` and `queue_oldest_pending_age_seconds`.

**Intuition.** XLEN is the number of the last ticket issued at the laundromat — it always grows, even
when everything has been washed. Lag is the bags in the back room that nobody has touched yet. Pending
is the bags in the machines plus the ones an employee set aside "for themselves" next to their machine.
Age of the oldest is how long the oldest bag has been lying there.

**Why it matters.** **Age of the oldest** is the best single SLO signal for a queue: length tells you
how much work there is, age tells you how long the customer waits. With tasks of different lengths the
same queue length means completely different waits (10 summaries of 1 s vs 10 analyses of 150 s). Alert
on age, not on length.

**Common mistake.** Alerting on `XLEN` — it grows monotonically, so it either always fires or someone
raises the threshold so high that it never fires.

---

## Prefetch hides the queue

**Definition.** **Prefetch** — the worker pulls more tasks from the broker than it is currently
running, "just in case", so it does not wait for the network when it takes the next one. In
taskiq-redis this is the `xread_count` parameter. Prefetched tasks stop being "in the queue" (lag
drops) even though nobody is running them yet — they sit in the memory of one process as pending.

**Intuition.** A laundromat employee who takes 100 bags from the back room and lines them up next to
their own machine. The back room looks empty, the colleague next door stands idle, and the customers
wait just the same.

**Why it matters.** Ex. 14 (F15): with a prefetch of 100, lag was **0** for the whole test — the queue
looked "empty" even though tasks were waiting (and ending with errors). After setting the prefetch equal
to `max-async-tasks` (4): lag peaked at **190** and then fell to 0 at ~7/s — the queue became visible
and drained as the calculation predicts. Prefetch also hoards work: one process can take tasks that the
other would have run right away.

**Common mistake.** Looking at lag without pending. A healthy queue is lag going down and **pending ≈
concurrency**; pending ≫ concurrency means tasks are waiting on the worker side, outside the lag metric.

---

## Response cache

**Definition.** A **cache** stores the result of a call under a key (in the course: a hash of the
normalized FAQ question) for a **TTL**. A hit does not call the LLM; a miss calls it and stores the
result. The **hit ratio** *h* reduces traffic to the provider: λ_provider = (1 − h) · λ. The
application counts the results in `app_cache_total{outcome="hit"|"miss"|"shared"}`.

**Intuition.** A "most frequently asked questions" board at the service window: to the question "what
is the deadline for reporting damage?" the board answers, not the clerk.

**Why it matters.** For repeatable questions (FAQ, templates) a cache lowers both the cost and the load
on the limits — with an ideal single-flight the number of LLM calls is **the number of distinct keys ×
(time / TTL)**, regardless of traffic. In the final: 5 questions × 240 s / TTL 30 s ≈ **40** required
calls (measured after the fix: 36).

**Common mistake.** Caching LLM answers where the answer depends on context (a specific claim, customer,
history) — hits will be rare, and every hit may be wrong. A cache makes sense for data where the same
question is supposed to get the same answer.

---

## Cache stampede and single-flight

**Definition.** A **cache stampede** (thundering herd) — a key expires (or does not exist yet), and N
concurrent requests for the same key all see a miss and **each** calls the LLM: N calls instead of one,
in a wave every TTL. **Single-flight** — only the first request computes the result, the others **wait
for its result** (within a process: a shared `asyncio.Future` per key; across processes: a Redis lock
`SET key NX PX time`, 30 s in the course solution — longer than the deadline of short calls).

**Intuition.** On the news that "we're out of coffee", ten people go to the store at once.
Single-flight: one goes, the rest wait for them by the coffee machine.

**Why it matters.** Ex. 15: 50 concurrent identical questions — **50** LLM calls, p99 4.6 s → with
single-flight **1** call (49 "shared"), p99 1.32 s. In the final, the stampede compounds with other
flaws: with 4 slots (a pool that is too small) the request that computes the result waits longer for a
slot, so the "miss" window lasts longer and there are **290** misses instead of ~40. A queue in front of
the LLM lengthens the stampede — two flaws multiply instead of adding up.

**Common mistake.** Single-flight without a time limit. When the only computing request hangs or is
cancelled, everyone waiting hangs along with it — the lock must expire, and the leader's error must reach
the waiters (or one of them takes over the computation).

---

## Batching: window and size

**Definition.** **Batching** glues many small requests into a single LLM call (in the course: assessing
the priority of many claims with one call, endpoint `POST /claims/{n}/priority`). Two parameters:
- **window** — how long to wait for the batch to fill;
- **maximum size** — the most requests allowed in one batch.

The batch is sent when the window elapses **or** the batch is full. Average batch size ≈
**min(λ × window, max)**; the extra latency of a single request is ≤ the window. The application
reports the size in the histogram `app_batch_size` (default OTel buckets: 0, 5, 10, 25, 50, …). Look at
the average `sum(app_batch_size_sum) / sum(app_batch_size_count)` — with a few rare batches
`histogram_quantile` interpolates inside a wide bucket and makes up a size (batches of 1 and 30 give a
"p99" ≈ 49.5).

**Intuition.** An airport shuttle bus: it leaves every 10 minutes or when it is full. With little
traffic you ride alone, but after waiting 10 minutes; with heavy traffic — quickly, in a full bus. A bus
that is too big takes longer (more stops), and when it breaks down, the whole thing is stuck.

**Why it matters.** Batching reduces the number of **requests** to the provider (the RPM limit,
per-call overhead), but it does not reduce the number of **tokens** to process (ITPM/OTPM) — and it
lengthens a single call. Ex. 16, a 2 s window and a batch of up to 100 (the skeleton):
- a single request under low traffic: **2.78 s** (it waits the whole window);
- 30 requests/s: 30 × 2 s ≈ **60** requests in a batch, 5 calls, p99 4.5 s.

After changing to a 50 ms window and a batch of ≤ 16: a single request **0.54 s**; at 30/s the batches
have p50 2 (30 × 0.05 ≈ 1.5), max 5, 146 calls, p99 1.14 s. There are more calls, but each is short, and
the tail is gone.

**Common mistake.** Choosing the window and size for throughput without looking at the token limits. A
batch of 100 claims at ~80 tokens each is 8,000 input tokens in one request: at an ITPM of 60,000 (the
`limits` profile) 7.5 such batches fit in a minute, and a single 429 rejects the **whole** batch — 100
requests at once. A batch of ≤ 16 is ~1,280 input tokens: the error affects fewer requests, and the
token limit is consumed more evenly.

---

## How it all fits together (map)

```
            ┌─ cache (TTL, key) ── hit ──► answer without the LLM: λ_provider = (1−h)·λ        [ex. 15]
 request ───┤    miss ──► single-flight (a Future in the process + SET NX PX across processes)
            │              (without it: N misses → N calls; a longer wait for a slot = a bigger stampede)
            ├─ batching: window ∧ size → batch ≈ min(λ·window, max); +≤ window of latency;     [ex. 16]
            │              fewer requests (RPM), the same tokens (ITPM/OTPM), a 429 = the whole batch
            └─ task queue (taskiq + Redis Streams) → worker: L = workers × max-async-tasks      [ex. 14]
                   metrics: lag (the real queue) · pending (≈ concurrency) · age of the oldest (SLO)
                   traps: XLEN ≠ queue · prefetch ≫ concurrency hides the queue · L > provider capacity = 529
```

Now move on to ex. 14.
