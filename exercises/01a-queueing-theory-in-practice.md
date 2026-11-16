# 01a. Reading: queueing theory in practice

A reading, not an exercise — no tasks and no "done" criteria. The goal is to translate
Little's law and the utilization curve from `00-theory.md` into concrete
activities from Block I: how to measure capacity, how to find the knee on a ramp,
how many slots to plan for, and what happens when requests lasting seconds and requests
lasting minutes meet in one pool. Every concept follows the same pattern:

> **Definition** → **Intuition/analogy** → **Why it matters** → **Common mistake**

Come back here whenever things stop adding up. Short definitions are in `glossary.md`.

---

## Capacity and the bottleneck

**Definition.** The **capacity** of a service center is the highest throughput it can
sustain: **X_max = c / S** (c — the number of servers/slots, S — the average
service time). The capacity of the whole request path is the **minimum** of the capacities of the
service centers it passes through — the service center that sets that minimum is the **bottleneck**.
For the summary path in this course there are several candidates:

| Service center | Capacity | Example from the course |
|---|---|---|
| LLM semaphore | slots / S | 4 / 1.06 s ≈ 3.8/s (skeleton), 32 / 1.06 s ≈ 30/s (after ex. 6) |
| httpx2 connection pool | max_connections / S | 8 / 1.06 s ≈ 7.5/s with a semaphore of 64 (ex. 6 variant) |
| provider token limit | OTPM / output_tokens | 12,000 / 200 = 60/min = 1/s (`limits` profile, ex. 8) |
| provider capacity | concurrent_generations / S | 8 generations + a queue of 8, then 529 (`overload` profile, ex. 9, 14) |
| gunicorn `-k sync` processes | processes / S | 29 / 3.5 s ≈ 8.3/s (ex. 7) |
| event loop with blocking | 1 / S | sync client: 20 calls of 0.5 s = 10 s in series (ex. 4) |

**Intuition.** A pipe made of sections with different diameters: the flow is set by the
narrowest section. Widening the others changes nothing — except that more water
collects in front of the narrowest one.

**Why it matters.** Before you add slots, work out whether the semaphore is the bottleneck.
In ex. 8 the application has 32 slots (30/s), but the `limits` profile
lets through 1 summary/s — adding slots will only increase the number of 429s.
In the ex. 6 variant a semaphore of 64 with a connection pool of 8 gives the provider at most
8 concurrent generations — the bottleneck is the pool, not the semaphore.

**Common mistake.** Computing capacity from a request's **total time**
instead of its **service time** at a given service center. When a request waits 30 s for a slot and
runs for 1 s, the slot is busy for 1 s, not 31 s — you put 1.06 s into X_max = c / S. The reverse
holds for the anyio thread pool: a thread is busy for the entire duration of the
synchronous call, including waiting for the network.

---

## Measuring capacity: the ramp

**Definition.** A **ramp** is an open-model test in which the arrival rate
grows in steps (in k6: the `ramping-arrival-rate` executor, in the course
`k6/ramp.js` with the parameters `FROM`, `TO`, `STEP_RPS`, `STEP_S`). At each step you
read, in a window equal to the step length: the **achieved rate**, the **occupancy**
of the resource (`llm_inflight`) and the **wait** (p90 from the
`llm_queue_wait_seconds` histogram). Capacity is the rate at which the achieved
throughput stops keeping up with the requested one.

**Intuition.** A treadmill stress test: the speed goes up every minute, you measure
your heart rate. For a long time it rises linearly, at some point it flattens out at a maximum;
beyond that the body "takes on debt" (lactic acid = the queue) that does not show
up right away in the running pace, only in how long it takes you to recover.

**Why it matters.** The ramp after ex. 6 (32 slots, summaries ~1.06 s; requested steps
4, 12, 20, 28, 36, 44/s, each ~22 s) gave, in consecutive 22 s windows from
Prometheus (the windows are not perfectly aligned with the steps — `rate()` smooths
the transitions):

| window | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| achieved rate | 8 | 15 | 20.5 | 29.2 | 29.8 | 30.2/s |
| `llm_inflight` max | 13 | 24 | 31 | **32** | 32 | 32 |
| wait p90 | 0 | 0 | 0 | 1.6 s | 6.1 s | 9.7 s |

Three independent signals show the same thing: the rate stalls at ~30/s, occupancy
sticks to 32, waiting breaks away from zero. Little's calculation
(32 / 1.06 ≈ 30.2/s) agrees with the measurement — the model is verified and you can
plan on it.

**Common mistake.** Steps that are too short, and blindness to the generator. With a 5 s step
the queue has no time to grow and the knee "shifts" to the right. Above
the knee the generator has its limits too: in the course's ramp at 36–44/s k6
reported 130 `dropped_iterations` and 45 `dial: i/o timeout` errors (the Docker
Desktop network under hundreds of new connections) — those are problems of the **generator**, not
of the application, and you report them separately.

---

## The knee of the curve: how to find it

**Definition.** The **knee** is the range of utilization in which the waiting time
goes from "negligible" to "growing faster than the load". A practical
definition for measurement: **the highest rate at which the wait p90 (or p99)
stays within budget**, e.g. ≤ 10% of the service time. Theoretically (M/M/c) the knee
falls closer to ρ = 1 the more servers there are and the lower the variability of the times.

**Intuition.** On a highway at 60% lane occupancy you drive freely,
at 85% — in waves, at 95% — every braking of a single car creates a jam
a mile long. The knee is the moment when the "waves" start by themselves.

**Why it matters.** For 32 slots the Erlang C calculation (00-theory) gives an average wait of
0.03 s at ρ = 0.8 (24/s), 0.15 s at ρ = 0.9 (27/s), 3.1 s at
ρ = 0.99 (30/s). The measurement on the ramp: wait p90 = 0 up to ~20/s, 1.6 s at
29.2/s. So the knee lies around **28–30/s** — about 90–97% of capacity
(30.2/s): with many slots and low variability of service times it is close to 100%.
For 4 slots (the skeleton) the same ρ gives a many times longer wait: few
servers = a gentle, early knee.

**Common mistake.** Looking for the knee in **average** latency. The average grows
late and gently (it is dominated by the mass of requests with no waiting); the tail (wait p90/p99)
breaks away earlier and more clearly. The second mistake: taking the knee from the total latency chart
when the service time itself changes with load (e.g. the provider slows down under traffic) —
then separate waiting from service.

---

## Capacity planning with headroom

**Definition.** **Capacity planning** is choosing the number of servers (slots,
processes, workers) so that at the expected traffic utilization
stays below the target **ρ_target** (usually 0.7–0.8):

> **c = ⌈ λ_peak · S / ρ_target ⌉**

plus a check that **every** service center on the path (connection pool, provider
limit, provider capacity) can handle the same traffic.

**Intuition.** A restaurant does not staff waiters for the average traffic of the whole day,
but for Saturday evening — and a few more, because someone will call in sick.

**Why it matters.** An example for summaries: a peak of 20/s × 1.06 s = 21.2 slots
on average. With ρ_target = 0.8: ⌈21.2 / 0.8⌉ = **27** slots; with 0.7 — **31**.
Choosing 32 slots in the course means ρ ≈ 0.66 at 20/s. The headroom covers:
- **variability** — arrivals are not even, service times have a tail;
- **peaks shorter than the metric window** — "an average of 20/s" over a minute may be
  40/s for 10 s;
- **retries** — every attempt is additional λ (ex. 9: uncontrolled, 3.65 attempts
  per request);
- **losing an instance** — when one of two processes dies, the other gets
  double the traffic.

The second half of the plan is the **upper bounds that you cannot change with slots**:
the provider limit (OTPM 12,000 → 1 summary/s in the `limits` profile), the provider
capacity (8 concurrent generations in the `overload` profile). Slots above that
ceiling will not increase throughput — they will increase 429s/529s.

**Common mistake.** "Let's give it 1,000 slots, that will be headroom." A slot with no backing in
the capacity of the next service center moves the queue further on, to where it is harder to see
and where you pay in errors: at the provider (529, ex. 14: 2 × 100
concurrent tasks against a capacity of 8 → 179/200 errors in 6 s). A concurrency limit
**is** a tool — it should match the capacity of what stands behind it.

---

## Planning for multi-minute calls

**Definition.** The same formula, but with S in minutes. For analyses (on average ~153 s)
at an arrival rate of 0.4/s you need on average L = 0.4 × 153 ≈ 61 slots, and with ρ_target =
0.8 — **77**. That is the number of calls in flight at the same time at the provider, each for
minutes.

**Intuition.** A parking lot: a car staying 5 minutes and a car staying 5 hours take up
the same amount of space, but the second one "consumes" sixty times more of it.

**Why it matters.** Such a result usually means that holding an HTTP request
synchronously for minutes is the wrong model. You have three options, all in the course:
1. **A separate pool for long requests**, sized to the capacity set aside for
   them (16 slots → 0.105/s) and **explicit rejection** of the excess (ex. 12: 42
   fast 503s instead of 30 abandonments after minutes).
2. **A task queue** — the client gets a task identifier immediately, a worker
   processes at its own pace, the backlog and its age are visible (ex. 14).
3. **A deadline per class** — short 30 s, long 330 s; a request that will not
   make it anyway does not occupy a slot (ex. 10).

**Common mistake.** A shared deadline for all classes. In a test from building
the course a 150 s deadline "saved" the median of the short requests, but killed **all** 7
long streams (120–300 s) — wasted work, a provider slot occupied
for nothing.

---

## Mixed traffic and head-of-line blocking

**Definition.** **Head-of-line blocking** is a situation
in which short requests wait behind long ones because they share the same queue and the same
servers. In a pool of c slots, c long requests are enough to drive the capacity for short ones
to zero for as long as they last. The variance of service times
dramatically lengthens the queue at the same average load.

**Intuition.** One line at the post office: in front of you three people are each sending 40
international parcels, and you only want to buy a stamp. A "letters only" window
(a separate pool) solves the problem without hiring more staff.

**Why it matters.** Two measurements from the course:
- **A semaphore of 8, mixed traffic** (0.5/s for 180 s: 75 short ~2 s, 10 with a long
  TTFT of 60–180 s, 7 with a long stream of 120–300 s): the short requests waited
  **p50 85 s**, p99 113 s; draining took 240 s after the end of the inflow.
- **A shared pool of 32** (ex. 12: short 4/s + long 0.4/s, 180 s): short requests'
  wait **p50 29 s / p99 131 s**, at t = 180 s 287 short requests are waiting, drain
  342 s. **Separate pools 32 / 16**: short requests' wait p99 = 0, overall p99 1.74 s.
  The long ones still do not fit — but that is a problem of their own capacity, not
  of the short ones.

Fixes, from the simplest: **separate pools (bulkheads) per class**, **separate
wait budgets and deadlines**, **moving the long requests to a task queue**.
Priorities in a shared queue help less than you would think: once the long requests have taken
all the slots, priority will not free a single one.

**Common mistake.** The diagnosis "the short requests are slow, so the provider slowed
down". The short requests' service time (`llm_call_duration_seconds{request_class="short"}`) is
fine — only the wait grows. Look at `llm_queue_wait_seconds` per
class and at `llm_inflight{request_class="long"}`.

---

## Steady state, warm-up and draining

**Definition.** **Steady state** — the period in which the averages (rate, occupancy,
wait) have stopped changing. A capacity measurement makes sense only in it. Before
it comes the **warm-up** (pools fill up, connections get established), after
the end of the inflow — **draining**. When λ > X_max there is **no** steady state.

**Intuition.** You do not measure fuel consumption in the first 30 seconds after
starting a cold engine, or on a highway exit ramp.

**Why it matters.** From Little's law: steady state arrives after a time on the order of a few W.
For summaries (W ~1 s) a few seconds are enough; for analyses (W ~150 s) —
**a few minutes**. That is why the tests with long calls in the course last ≥ 180 s
of inflow plus draining (6.5–10 minutes in total), and the report includes the state after the end of
the inflow: how many are waiting, the age of the oldest, the drain time.

**Common mistake.** A 60-second test with requests lasting 150 s. No
long request will finish during the inflow, all results
come from the "tail" after the test — and the default k6 timeout (60 s) would cut them off anyway.

---

## Little's law as a measurement consistency check

**Definition.** Given two of the three measurements (L, λ, W), you compute the third and
compare it with its independent measurement. A discrepancy = one of the measurements is wrong
or there is a queue you are not measuring.

**Intuition.** Bookkeeping: income, expenses and the account balance must agree.
If they do not — there is an unrecorded invoice somewhere.

**Why it matters.** Examples from the course:
- the task queue (ex. 14): 2 processes × 4 tasks = L = 8, 200 tasks in 28.7 s →
  X = 6.97/s → W = 8 / 6.97 ≈ 1.15 s per task — consistent with the summary time;
- gunicorn (ex. 7): UvicornWorker 450 requests, the last after 34.6 s → achieved
  450 / 34.6 = 13.0/s, although 15/s was requested — the rest is waiting and the tail;
- the ex. 6 variant with a connection pool of 8: the semaphore lets 64 through, and at the provider
  `mock_llm_generating` ≤ 8 — Little's law for the provider says that someone is holding the rest
  in a queue in front of it; that queue is the httpx2 pool.

**Common mistake.** Comparing averages from different time windows (λ from a
minute, W from the whole test). The windows must be the same.

---

## How it all fits together (map)

```
 service center capacity:  X_max = c / S      path: min(service centers) = bottleneck
        │                                    (semaphore | connection pool | OTPM | provider capacity | processes)
        ▼
 ramp (ex. 3): rate stalls + inflight = c + wait p90 breaks away  →  knee ≈ 90–97% of X_max (c = 32)
        │
        ▼
 plan: c = ⌈λ·S / ρ_target⌉, ρ_target 0.7–0.8  +  check the ceilings that slots cannot raise
        │
        ├─ S in minutes → L in the tens → separate pool + rejection (ex. 12) / task queue (ex. 14)
        └─ mixed traffic → head-of-line → separate pools per class, deadline per class (ex. 10, 12)
 check: L = λ·W at every service center; a mismatch = an unmeasured queue
```

Now move on to ex. 1.
