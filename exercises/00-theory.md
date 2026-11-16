# 00. Theory: an LLM application under load — waiting, queues, capacity

A big primer, not an exercise — no tasks and no "done" criteria. The goal is to
build a map of concepts before you start exercises 1–18. Every concept follows the
same pattern:

> **Definition** → **Intuition/analogy** → **Why it matters** → **Common mistake**

Come back here whenever things stop adding up. Short definitions of all terms are
in `glossary.md`. Narrower readings wait before the topic blocks:
`01a-queueing-theory-in-practice.md`, `04a-asyncio-loop-and-pools.md`,
`08a-limits-retries-timeouts.md`, `12a-backpressure-and-streaming.md`,
`14a-task-queues-cache-batching.md`. This document gives the common foundation
for all five.

Context: throughout the course you diagnose one application — a **claims service
desk assistant** (insurance). It is a FastAPI service on asyncio that calls a
language model for every claim: it summarizes the claim, classifies it, writes a
reply to the customer, assesses its priority, runs a multi-minute analysis, and
answers frequently asked questions (FAQ). Nearly the whole lifetime of a request is
**waiting for the LLM** — the application's CPU is idle, and yet the application
can still "clog up". The LLM provider is a **mock** — our own server compatible
with the Messages API, which the official `anthropic` SDK talks to; it has
repeatable latency distributions, limits, 429/529 errors, streaming and
minute-long profiles. In one exercise you compare it with the real Claude.

The numbers in this document were measured in the course environment (macOS +
Docker Desktop, Python 3.13, FastAPI 0.162, uvicorn 0.54, anthropic 2.3.0 on httpx2
2.16, k6 2.3, mock in a container) or derived by a calculation shown in the text.
On different hardware they will differ — the orders of magnitude and the shapes of
the curves stay.

---

## Latency, throughput, concurrency

**Definition.** Three quantities that describe any system under load:
- **Latency** (response time, *R*) — how long one request takes, from arrival to
  the last byte of the response. It is measured by the client (or by the server —
  those are two different numbers, more on that later).
- **Throughput** (*X*) — how many requests per second the system **finishes**. Not
  how many **arrive** — that is the **arrival rate** (*λ*). As long as the system
  keeps up, X = λ; when it does not, X stops at capacity, and the difference
  λ − X lands in the queue.
- **Concurrency** (*L*) — how many requests are in the system **at the same time**
  (waiting and being served). In asyncio it is the number of live tasks, in a pool
  — the number of busy slots, at the provider — the number of generations in
  progress.

**Intuition.** A highway: latency is the time to drive a stretch, throughput is how
many cars per minute pass the toll gate at the end, concurrency is how many cars are
on the stretch right now. A traffic jam is when more cars enter than leave: the
throughput at the gate does not change, only the number of cars on the stretch and
the travel time grow.

**Why it matters.** Every exercise in the course boils down to the question of which
of these three numbers is going wrong, and why. The three quantities are tied
together by Little's law (below) — knowing two, you compute the third and check
whether the measurement "adds up".

**Common mistake.** "Throughput = the number of requests sent per second". A report
from the load generator that shows *how many it sent* says nothing about *how much
the system did*. In exercise 4 the application receives 6 requests/s and finishes
2.05/s — the rest waits in the socket and in the event loop. Always report the
**achieved** rate (completed / time to the last response), not the target rate.

---

## Waiting vs service

**Definition.** You split response time into two parts:
**R = waiting time (W_q) + service time (S)**. Service is the work someone actually
does for the request (here: generation at the provider, a few milliseconds of
application code). Waiting is the time the request stands in the queue for a
**resource**: a semaphore slot, a connection in the pool, a thread in the pool, a
gunicorn process, the provider's "capacity".

An LLM application adds a third kind of time: **waiting for a response from the
outside**. From the application's point of view, generation at the provider is
"service", but the application's CPU does nothing during that time — the coroutine
is suspended on `await`. That is why in this course "waiting" always means **waiting
for a resource before the call**, and "service" means **the LLM call itself** (the
`llm.call` span). The application reports them separately: the
`llm.queue.wait_ms` attribute and the `llm_queue_wait_seconds` histogram (waiting
for the semaphore), and `llm_call_duration_seconds` (the call).

**Intuition.** A government office: the ticket from the machine and the time at the
window. The clerk serves everyone in 3 minutes — that is S. If you spent an hour in
the office, then 57 minutes of it was waiting, and optimizing the work at the
window (S from 3 to 2.5 minutes) will not help. You need more windows or
fewer people at once.

**Why it matters.** This is the first diagnostic decision: is the request slow
because **service** is slow (the provider generates for a long time, a slow first
token), or because it **waits** (a pool that is too small, a provider limit, a queue
behind long requests)? The fixes are completely different. In exercise 6, with 4
slots and traffic of 20/s, waiting has a p50 of 32 s, while the LLM call has a p50 of
1.06 s — 97% of the request's time is the queue.

**Common mistake.** Looking for the cause in the CPU profile. Waiting does not use
CPU — a suspended coroutine and a thread in `Condition.wait` are invisible in the
profile or look like "idle". Waiting shows up in the trace (the gap between arrival
and `llm.call`, the `llm.queue_wait` span) and in resource metrics (occupancy =
limit).

---

## The system as a network of queues

**Definition.** A **queue** is a place where requests wait for a **server** (in the
queueing-theory sense: anything that serves one request at a time — a slot, a
thread, a connection, a process). A set of *c* identical servers with one queue is a
**service center**. An LLM application is a **network** of such service centers
placed one after another — a request passes through each of them and can wait in
each:

```
 client (k6)
   │  socket backlog (kernel) ── gunicorn / uvicorn process        [ex. 7]
   ▼
 asyncio event loop (1 thread)  ◄── blocking the loop: everyone waits  [ex. 4]
   │
   ├─► anyio thread pool (40)     ◄── synchronous code in `def`        [ex. 5]
   │
   ├─► queue limit / load shedding (503 + Retry-After)                 [ex. 12]
   ▼
 LLM semaphore (slots per class: short / long)                         [ex. 1, 6, 12]
   │
   ├─► rate limiter (RPM / ITPM / OTPM per provider headers)           [ex. 8]
   ▼
 httpx2 connection pool (max_connections)                              [ex. 6]
   │                                     ┌─► Redis task queue + worker [ex. 14]
   ▼                                     │
 LLM provider: provider queue → generation capacity (e.g. 8 at once) → 429/529 [ex. 8, 9, 11]
```

Every service center has its own **limit** (size), its own **queue** (explicit or
hidden) and its own way of **failing** once it overflows: the queue grows without
bound, the request gets an exception (`PoolTimeout`), an HTTP error (429, 529, 503),
or the connection is dropped (socket backlog full).

**Intuition.** An airport: the check-in queue, security, the gate, the runway. A
passenger can wait at every point; the fact that check-in is fast does not help if
security has a single lane. The **bottleneck** is the service center whose
utilization reaches 100% first — behind it traffic is "thinned out", in front of it
the queue grows.

**Why it matters.** The map of service centers is a list of places to look for
waiting, and a list of counters you must have: for each service center, the
**occupancy** (how many slots are busy), the **waiting** (how many are in the queue)
and the **age of the oldest waiting request**. The course application exposes them
for the semaphore (`llm_inflight`, `llm_waiting`, `llm_oldest_waiting_age_seconds`),
the mock — for the provider (`mock_llm_generating`, `mock_llm_provider_queue`,
`mock_llm_oldest_inflight_seconds`), and the task-queue exporter — for Redis
(`queue_lag`, `queue_oldest_age_seconds`).

**Common mistake.** "We only have queues where it says `Queue`". Every limit creates
a queue, including a hidden one: `asyncio.Semaphore` keeps a list of waiting
coroutines, the httpx2 pool — a list of those waiting for a connection, anyio — for
a thread token, the kernel — for `accept()`. The most dangerous ones are those you do
not measure: in exercise 6 a connection pool (8) smaller than the semaphore (64)
creates a queue that the `llm.queue_wait` span does not show at all — the time spent
waiting for a connection is counted as part of the "LLM call". The proof only comes
from the counter on the provider's side: `mock_llm_generating` never exceeds 8.

---

## Little's law

**Definition.** For any stable system (one that in the long run finishes as much as
it receives), on average:

> **L = λ · W**

where **L** is the average number of requests in the system, **λ** is the average
arrival rate (= throughput, when the system keeps up), **W** is the average time in
the system. The law does not depend on distributions, on the service order, or on
the number of servers. It works for the whole system and for each service center
separately (e.g. for the semaphore alone: L = the number of busy slots, W = the LLM
call time).

**Intuition.** A bar: 30 people arrive per hour, each stays 2 hours on average → on
average there are 60 people inside. You do not need to count anyone at the door.

**Why it matters.** Three uses, all of them in the course:

1. **Capacity from pool size.** A service center with *c* slots and service time *S*
   cannot pass more than **X_max = c / S**. After exercise 6 the short-class
   semaphore has 32 slots, and a summary takes 1.06 s: X_max = 32 / 1.06 ≈
   **30.2/s**. The ramp in exercise 3 measures exactly that: the rate grows 8 → 15 →
   20.5 → 29.2 → 29.8 → 30.2/s and stops, `llm_inflight` reaches 32 and sticks.
   With 4 slots (the skeleton) X_max = 4 / 1.05 ≈ **3.8/s** — which is why in
   exercise 2 traffic of 4/s is enough for the queue to grow.
2. **Pool size from traffic.** How many slots do you need for 20 summaries/s?
   L = 20 × 1.06 = **21.2** busy on average. Fewer than 21 slots = the queue grows
   without end; exactly 22 = the system is at its limit, with huge waiting (see "the
   knee" below). You compute the headroom in reading 01a.
3. **Measurement consistency check.** In exercise 7 gunicorn receives 15 requests/s
   at 3.5 s each → L = 15 × 3.5 ≈ **52** requests at once. Synchronous workers
   handle one request per process; 29 processes give X_max = 29 / 3.5 ≈ 8.3/s
   (measured 9.05/s — some of the calls were shorter). Two UvicornWorker processes
   with 32 slots each give 64 / 3.5 ≈ 18.3/s > 15/s — it fits.

**Little with W measured in minutes.** The law knows no units, but the consequences
of scale are brutal. An analysis takes ~153 s on average (generation U[60, 240] s +
a few seconds of TTFT). With an arrival rate of just **0.4 analyses/s**:
L = 0.4 × 153 ≈ **61** analyses run at once. A pool of 16 slots for long requests
gives X_max = 16 / 153 ≈ **0.105/s** — four times too little. In exercise 12, after
180 s of inflow: 73 long requests arrived, the backlog is 16 in progress + 46
waiting (calculation: (0.4 − 0.105) × 180 ≈ 53 excess). The same calculation for
W = 120 s of provider silence (exercise 10): 2 requests/s × 120 s = 240 slots needed
— 32 slots fill up in 16 s, and then everyone waits.

**Common mistake.** Applying Little's law to an unstable system. When λ > X_max, the
"average L" does not exist — the queue grows linearly with test time, and every
"average latency" in the report depends on how long the test lasted. The second
mistake: mixing the input λ with the output X. In an overloaded system use X
(achieved) and the W of completed requests — otherwise the calculation will not
close.

---

## Utilization and waiting time: the knee of the curve

**Definition.** The **utilization** (*ρ*) of a service center is the fraction of time
its servers are busy: **ρ = λ · S / c**. The key phenomenon in queueing theory:
waiting time does not grow linearly with ρ, but like **1 / (1 − ρ)** — slowly at low
load and sharply as ρ approaches 1. The point where the curve "bends upward" is the
**knee**.

The simplest model, **M/M/1** (Poisson arrivals — independent arrivals, exponential
service time, one server, an unbounded queue), has closed-form formulas
(μ = 1/S — the service rate):

> **W = 1 / (μ − λ) = S / (1 − ρ)**  **W_q = ρ · S / (1 − ρ)**  **L_q = ρ² / (1 − ρ)**

Interpretation: at ρ = 0.5 a request spends **2×** the service time in the system,
at 0.9 — **10×**, at 0.99 — **100×**. For S = 1.06 s (a summary):

| ρ | W (total) | W_q (waiting) | W / S | L_q (average in the queue) |
|---|---|---|---|---|
| 0.50 | 2.12 s | 1.06 s | 2 | 0.5 |
| 0.70 | 3.53 s | 2.47 s | 3.3 | 1.6 |
| 0.80 | 5.30 s | 4.24 s | 5 | 3.2 |
| 0.90 | 10.6 s | 9.54 s | 10 | 8.1 |
| 0.95 | 21.2 s | 20.1 s | 20 | 18 |
| 0.99 | 106 s | 105 s | 100 | 98 |

**M/M/c** (the same arrivals, *c* servers, a shared queue) behaves qualitatively the
same, but the knee moves **to the right and gets sharper** the more servers there
are. Many servers "smooth out" random bursts of arrivals: when one is busy, another
is just becoming free. The calculation (the Erlang C formula, the course's
verification script) for c = 32 and S = 1.06 s:

| ρ | λ | P(must wait) | W_q |
|---|---|---|---|
| 0.70 | 21.1/s | 4% | 0.004 s |
| 0.80 | 24.2/s | 16% | 0.03 s |
| 0.90 | 27.2/s | 46% | 0.15 s |
| 0.95 | 28.7/s | 70% | 0.46 s |
| 0.99 | 29.9/s | 93% | 3.1 s |

Compare with M/M/1 at ρ = 0.9: there, waiting is 9× the service time, here 0.14×.
But at 0.99 waiting explodes anyway. The ramp from exercise 3 shows it live: up to
~20/s the p90 of waiting is 0, at 29.2/s (ρ ≈ 0.97) it is 1.6 s, at 30.2/s — 9.7 s
and growing with every second of the test.

**Variability** is the second, equally important factor. Waiting time grows with the
variance of arrivals and of service times. Traffic of "all summaries at ~1 s" is
low variance; mixed traffic of "80% at 1 s + 20% at 60–240 s" is gigantic variance —
at the same average ρ the queue is many times longer, and short requests wait behind
long ones (head-of-line blocking, reading 01a, exercise 12).

**Intuition.** A shop checkout at 50% utilization: you usually walk up right away,
sometimes you wait for one person. At 95% someone is always standing there, and one
person with a full cart (high variance) holds up the whole queue for a quarter of an
hour. Ten checkouts with one shared queue (M/M/c) do much better than ten checkouts
with separate queues — but only as long as the cart with a quarter of an hour of
shopping does not end up in the shared queue with the baskets.

**Why it matters.** It explains why "the system runs at 85% and it's fine" can turn,
one day, into "p99 = a minute" after traffic grows by 10%. It also explains why you
plan capacity **with headroom** (target ρ of 0.7–0.8, not 0.95) and why you separate
request classes with different service times.

**Common mistake.** Treating the M/M/1 formulas as a numeric forecast for a real
system. Real LLM times are not exponential, k6 arrivals are not Poisson
(`constant-arrival-rate` sends exactly every 1/λ), and slots are not a single
service center. The model gives you the **shape** (where the knee is, what happens as
ρ → 1, that variance hurts) — you take the numbers from measurement (the ramp,
exercise 3).

---

## When the arrival rate exceeds capacity

**Definition.** When λ > X_max the system is **overloaded**: the queue grows
linearly at a rate of **λ − X_max**, and the waiting time of the k-th request (with
even arrivals) is approximately **k / X_max − k / λ**. There is no steady state.
After the inflow ends, the system keeps working for a long time — **draining** takes
about **backlog / X_max**.

**Intuition.** A bathtub with a drain of 3.8 l/s and a tap of 20 l/s. The water level
rises by 16 l/s, and it does not matter whether the drain is "fast" — what counts is
the difference.

**Why it matters.** Exercise 6, a calculation to check against the measurement: 4
slots, S = 1.06 s → X_max = 3.77/s; inflow of 20/s × 15 s = 300 requests. The queue
grows by 16.2/s. The 150th request waits 150 / 3.77 − 150 / 20 ≈ **32.3 s**
(measured p50: 32.3 s), the 297th — 297 / 3.77 − 297 / 20 ≈ **63.9 s** (measured
p99: 63.1 s). Draining 300 requests takes 300 / 3.77 ≈ 80 s, even though the inflow
lasted 15 s. With multi-minute calls the drain is counted in minutes: in exercise 12,
after the inflow ends, 16 long requests remain in progress and 8 waiting;
24 / 0.105 ≈ 230 s as an upper estimate (part of the work is already done) —
measured 213 s.

**Common mistake.** Ending the test together with the inflow. The k6 report from the
last second of inflow does not include the requests that are still waiting — and
those are the worst ones. The tests in the course measure the **backlog at the end of
inflow** and the **drain time** separately (`scripts/measure.py`), and k6 has a
`gracefulStop` longer than the longest request (the default 30 s would cut off
multi-minute requests in progress and falsify the result — measured while building
the course).

---

## Percentiles and the tail

**Definition.** A **percentile p** (p50, p90, p99) is the value below which p% of
measurements lie. p50 = the median — the "typical" request; p99 — 1 in 100 is worse.
The **tail** is the upper part of the distribution (p99, p99.9, max). Percentiles
must not be averaged (the average of the p99 of five instances ≠ the p99 of the
whole) — you compute them from the combined distribution, e.g. from a histogram:
`histogram_quantile(0.99, sum by (le)(rate(..._bucket[1m])))`.

**Intuition.** The average salary in a company with a CEO is meaningless; the median
says what a typical employee earns, p99 — what the board earns. Latency has the same
problem: a few requests of 2 minutes each will turn an "average of 1.5 s" into a
number that describes no one.

**Why it matters.** The tail is what users feel and what multiplies in a system. A
page that calls 10 services hits at least one p99 with a probability of
1 − 0.99¹⁰ ≈ **9.6%**, with 50 calls — **39.5%**. The tail is also the first place
where you see the queue: in the ramp from exercise 3 the p90 of waiting rises from
zero earlier than the median. And finally — in an LLM application the tail is
**by design**: analyses lasting 60–300 s are not an anomaly, but a separate class.
That is why the course reports percentiles **per class** (short / long), not in
total.

**Common mistake.** The p99 of a small sample. Of 300 requests, 3 lie above p99 — one
change in the sequence moves p99 by seconds. The second: a histogram with buckets
ending at 10 s for times measured in minutes — everything above lands in `+Inf` and
the quantile is "truncated". The course's histograms (e.g. waiting at the provider in
the mock) have buckets up to 300 s for exactly that reason.

---

## Open vs closed model and coordinated omission

**Definition.** A load generator works in one of two models:
- **Closed** — a fixed number *N* of "users" (in k6: VUs, the `constant-vus`
  executor); each sends a request, **waits for the response**, waits *Z* (think time)
  and sends the next one. Throughput results from the responses:
  **X = N / (R + Z)** (the response time law — Little for a closed loop).
- **Open** — requests arrive at a given rate λ, **independently** of whether the
  previous ones have finished (k6: `constant-arrival-rate`, `ramping-arrival-rate`).
  This is how most real traffic behaves: clients do not know about each other.

**Coordinated omission** is a measurement error of the closed model: when the system
slows down, the generator itself **holds back** sending (the VU waits for a
response), so it does not measure the requests that, in an open world, would have
arrived during that time and waited in the queue. The generator "coordinates" with
the system and omits exactly those measurements that would be the worst.

**Intuition.** Studying the queue in a government office with 4 interviewers, each of
whom walks in only after the previous one has left. They will never see a queue,
because they do not create one themselves — while real visitors all arrive at 8:00
at once.

**Why it matters.** Exercise 2, the same nominal rate of ~4 requests/s against a
capacity of ~3.8/s (4 slots):
- closed, 4 VUs with no pause: 3.75/s (calculation: 4 / 1.07 s ≈ 3.74), p99
  **1.57 s**, waiting 0 — "everything is OK";
- open, 4/s: achieved 3.52/s, p99 **4.41 s**, semaphore waiting p99 3.28 s — the
  queue grows, because ρ ≈ 1.05.

With a 1 s pause the same 4 VUs give 4 / (1.08 + 1) ≈ **1.92/s** (measured 1.92/s) —
"4 VUs" is not "4 requests/s". In the open model k6 has a `dropped_iterations`
counter: when there are not enough VUs to send a request on time, the measurement is
invalid (the generator itself became the bottleneck) — always check it.

**Common mistake.** "I gave it 100 VUs, so it's a test for 100 users and it's
realistic". 100 VUs with no pause at R = 1 s is ~100 requests/s, at R = 10 s —
10/s: the load shrinks exactly when the system has a problem. The capacity, SLO and
queue tests in the course are **open**; the closed model serves only as a
counterexample (and for modeling a worker pool, which really is closed — e.g. a
task-queue worker with `--max-async-tasks`).

---

## RED and USE for this application

**Definition.** Two metric checklists:
- **RED** (for services, "from the outside"): **R**ate — the request rate,
  **E**rrors — the error fraction, **D**uration — the time distribution
  (percentiles).
- **USE** (for resources, "from the inside"): **U**tilization — occupancy,
  **S**aturation — how much waits for the resource, **E**rrors — resource errors.

In this application:

| Layer | RED / USE | Metric in the course |
|---|---|---|
| endpoints | R, E, D | `app_requests_total{endpoint,request_class,outcome}`, `app_request_duration_seconds_bucket` |
| LLM semaphore | U, S | `llm_inflight{request_class}` vs the number of slots; `llm_waiting`, `llm_oldest_waiting_age_seconds`, `llm_queue_wait_seconds` |
| LLM call | D, E | `llm_call_duration_seconds{provider,outcome}`, `llm_ttft_seconds` |
| HTTP to the provider | R, E | `llm_http_attempts_total`, `llm_http_responses_total{status}` (429, 529) |
| event loop | S | `app_event_loop_lag_seconds`, `/diag/ping` |
| provider (mock) | U, S, E | `mock_llm_generating`, `mock_llm_provider_queue`, `mock_llm_requests_total{status}`, `mock_llm_cancelled_total` |
| task queue | S | `queue_lag`, `queue_pending`, `queue_oldest_age_seconds` |
| client (k6) | R, D | `k6_http_reqs_total`, `k6_http_req_duration_p99`, `k6_dropped_iterations_total` |

Important: `outcome` distinguishes **ok, rejected, deadline_exceeded, cancelled,
provider_timeout, provider_rate_limited, provider_error**. An "error" in a system
with backpressure is several different things: a fast 503 from us is **healthy** (a
refusal), a 504 after a minute is not.

**Intuition.** RED is a patient's thermometer (fever or no fever), USE is the organ
tests (which organ is overloaded). First RED tells you *that* something is wrong and
*where* (which endpoint, which class); then USE points to *which resource* is
saturated.

**Why it matters.** It lets you start every diagnosis with a cheap overview instead
of random digging: "the p99 of short requests went up" (RED) → "the short class's
`llm_inflight` is stuck at the limit, `llm_waiting` > 0" (USE of the semaphore) →
"at the provider, `generating` is far from its capacity" → the bottleneck is on our
side (exercise 6, the final).

**Common mistake.** Looking only at **U** without **S**. A resource that is 100% busy
with no queue is a perfectly loaded resource; the problem is saturation — how many
wait and for how long. And the other way around: the semaphore can be at 4 busy out
of 4 while the provider is "underloaded" — that means the limit is the semaphore, not
the provider.

---

## LLM specifics: TTFT, tokens, minutes, limits, cost

**Definition.** An LLM call differs from a typical database call:
- **TTFT** (*time to first token*) — the time from sending the request to the first
  fragment of the response; it includes the provider's queue and the processing of
  the input. On the real Claude (Haiku 5.5, checked while building the course) the
  median is 0.48–0.72 s, with a tail up to ~1.2 s.
- **Generation speed** (tokens/s) — after the first token the rest flows at a
  constant speed: realistically ~225–300 tokens/s. Total time ≈ TTFT +
  output_tokens / speed: a 700-token response ≈ 0.48 + 700 / 225 ≈ 3.6 s (measured
  3.62 s). The mock by default: a log-normal TTFT with a median of 450 ms, 250
  tokens/s.
- **Times from seconds to minutes.** Long tasks (analyzing a whole claim file,
  reasoning models) take **60–300 s**: they either stay silent for a long time before
  the first token (a long TTFT), or generate for a long time (a long stream), or make
  pauses. This is a full-fledged traffic class, not an anomaly.
- **Provider limits** — counted per minute: **RPM** (requests), **ITPM** (input
  tokens), **OTPM** (output tokens). Exceeding them → **429** with `retry-after` and
  `anthropic-ratelimit-*-remaining/-reset` headers. A separate case is **529
  overloaded** — the provider has no free capacity (in the SDK `OverloadedError`, a
  class distinct from `RateLimitError`).
- **Cost** — you pay for input and output tokens (Haiku 5.5: $0.10 / $0.50 per
  million). A retry sends the input again; an abandoned generation consumed the
  provider's capacity and the token limit.

**Intuition.** An LLM provider is a print shop working to order: first you wait for
them to accept the job and prepare the machine (TTFT), then the pages come out at a
steady pace (tokens/s). The print shop has a limit of jobs and pages per minute for
your company (RPM/OTPM) and its own machine capacity shared by all customers (529).
Every job repeated "just in case" costs a second time.

**Why it matters.** The token limit is also capacity, and it is computed like Little:
the mock's `limits` profile has an OTPM of 12,000; a summary is 200 output tokens →
12,000 / 200 = **60 summaries/min = 1/s**, regardless of the number of slots.
Traffic of 3/s × 60 s = 180 requests against a capacity of 60 — in exercise 8 the
skeleton collects 133 responses with status 429 from the mock. After the fix the 429s disappear,
but **the excess waits on our side** (waiting p99 58 s) — a client-side limiter does
not increase capacity, it moves the queue to a place you control.

**Common mistake.** "You can't see limits at a real provider, so there aren't any".
On the account used to build the course the limits were so high (RPM 13,000, OTPM
2 M) that a 429 was practically unreachable — which is why you practice limits on the
mock. In production with a lower tier, or with large batches (ITPM), it is the first
wall you will hit.

---

## Multi-minute calls

**Definition.** A request whose service time is counted in minutes (in the course:
60–300 s) changes all the earlier calculations by one or two orders of magnitude: it
occupies a semaphore slot, a connection and a provider slot **for minutes**, and
every timeout error or retry costs **minutes**.

**Intuition.** A car wash where a bus drives in every now and then. The car wash is
"fast" until the buses take up all the bays — then the passenger cars stand for half
an hour.

**Why it matters.** The course treats them as the main case, not a footnote:
- **Slot occupancy in minutes.** L = λ · W: at W = 153 s even 0.4/s gives 61
  parallel analyses (above). Every call holds a slot ~150 times longer than a
  summary.
- **Head-of-line blocking.** In a shared pool of 32 slots (exercise 12, short 4/s +
  long 0.4/s) short requests wait **p50 29 s, p99 131 s** with a service time of
  ~1 s — because the analyses ate the slots. Separate pools (32 / 16): the short
  requests' waiting p99 = 0.
- **Timeouts.** The SDK's default read timeout is 600 s; the k6 timeout — 60 s;
  gunicorn with sync workers kills a worker after 30 s. Each of them "cuts" a
  multi-minute request differently (reading 08a, exercise 10).
- **Retries multiply minutes.** 4 analyses with 90 s of silence, a 60 s timeout and
  the SDK's default 2 retries: 3 × 60 s ≈ 180 s of waiting and a 504 error after
  181.6–191.6 s, 10 abandoned generations at the provider (exercise 10).
- **Cancellation.** A client that disconnected after 20 s does not release the slot
  on its own: without cancellation the provider generates work nobody is waiting for, for another
  173 s; with cancellation the slot returns in 0.7 s (exercise 10).
- **Drain.** After the inflow ends, long requests keep working for minutes — you
  measure the age of the oldest (`mock_llm_oldest_inflight_seconds`) and the backlog
  after the traffic has ended, not only during it.

**Common mistake.** Testing on a seconds-long profile and extrapolating. A profile of
"everything in a second" will not uncover the 60 s timeout in k6, the 30 s one in
gunicorn, a ping that keeps the connection alive, or the fact that the SDK's
`timeout` is not a total limit. The seconds-long profile in the course is only for a
quick smoke test; the exercises on timeouts, backpressure and the final run
wall-clock for several minutes.

---

## How to read traces, metrics and profiles in this course

**Definition.** Three kinds of telemetry (all through OTel to Grafana: Tempo,
Prometheus, Pyroscope):
- **Trace** — a tree of **spans** of one request: each span has a start, an end,
  attributes and a parent. It shows **where the request spent its time**, including
  time when nobody was computing anything. The structure in the application:
  ```
  POST /claims/{n}/summary            (root: app.request_class, app.outcome, llm.queue.wait_ms)
   ├─ llm.queue_wait                  (waiting for the semaphore — a sibling, not the parent of llm.call)
   └─ llm.call                        (llm.provider, llm.cb.state)
       └─ anthropic.messages.create   (the SDK's native span)
           └─ POST                    (httpx2: a single HTTP attempt)
  ```
  Gaps between spans are time nobody recorded: loop blocking, waiting in the
  connection pool, backoff between attempts. Several `POST` spans under one
  `anthropic.messages.create` = SDK retries.
- **Metrics** — aggregates over time (counters, histograms, gauges). They show
  **how much and how often** across all traffic: rate, percentiles, occupancy,
  queues. They will not tell you *which* request, but they will tell you *that* the
  problem affects 30% of traffic.
- **Profile** (Pyroscope) — samples call stacks and shows **which functions the
  threads are in** (CPU or wall-clock). It answers the question "what is the code
  doing".

**Intuition.** A trace is a recording from the camera following one customer in a
shop; metrics are the counter at the door and the bird's-eye camera; a profile is a
photo of what the employees are doing at a given moment. A customer standing in a
queue is in the recording (trace), in the statistics (the waiting metric), but not in
the photo of the employees.

**Why it matters.** Each kind answers a different question and has blind spots:
- A profile **does not see a suspended coroutine**. A request waiting 60 s on an
  `await` (semaphore, LLM, backoff sleep) does not occupy a thread — it is on no
  stack, in no profile mode. Checked while building the course: an `await` on the LLM
  is invisible in both the CPU profile and the wall-clock one.
- A profile **sees blocking**: a synchronous LLM client in an async handler is almost
  invisible in the CPU profile (0.4% — it waits on the socket, it does not compute),
  but not in the wall-clock one (13%, `SyncStream.read`). That is why in exercise 4
  the profile is only a confirmation; the main symptom is systemic (throughput,
  /health).
- A trace **will not show a queue where nobody put a span** — waiting in the httpx2
  connection pool has no span of its own (exercise 6), and the socket backlog is not
  in the trace at all. Resource metrics help there.
- Metrics **average**: a waiting histogram from mixed traffic without the
  `request_class` label will hide that short requests wait a minute.

**Common mistake.** "The profile shows 2% CPU in the handler, so the handler is not
the problem". In an I/O-bound application nearly everything that matters happens
**between** the samples of the CPU profile. The second: the `llm.queue_wait` span as
the **parent** of `llm.call` — then the call time is counted as waiting and the
reading is false; in the course waiting is a sibling of the call (exercise 1).

---

## Diagnosis method in this course

**Definition.** Every exercise and incident follows the same loop:
1. **Symptom from the outside** (RED, the k6 report — with the achieved rate and
   `dropped_iterations`).
2. **Hypothesis before observation** — before you open Grafana, write down what you
   expect to see and why (Little, the knee, ρ).
3. **Time breakdown** — the trace: waiting vs service vs TTFT vs gaps.
4. **Resource** — USE: which limit is stuck at its maximum and where the queue grows
   (on our side or at the provider).
5. **Calculation** — do the numbers add up with L = λW. If not, you are looking for a
   queue you do not measure.
6. **Fix and re-measurement** — the same traffic, the same test length, buggy vs
   fixed; plus the state after the inflow ends.

**Intuition.** A doctor: interview, hypothesis, examination, result, a check-up after
treatment. A hypothesis before the examination protects against "I see a chart, so I
know".

**Why it matters.** Queueing systems are counterintuitive: a fix in one place moves
the queue elsewhere (exercise 8: the 429s disappear, waiting on our side grows;
exercise 6: more slots with a connection pool that is too small change nothing).
Little's calculation and the measurement after the fix catch such shifts.

**Common mistake.** Comparing runs of different lengths or with a different traffic
model. In an overloaded system p99 grows with test length — two runs are comparable
only with the same inflow, duration and model.

---

## How it all fits together (map)

```
            λ (arrival rate, OPEN model)                      ex. 2: closed hides the queue
                 │
                 ▼
  ┌──────── service center: c slots, service time S ─┐        ρ = λ·S/c
  │ queue (W_q)  →  service (S)                      │        L = λ·W        (ex. 3)
  │                                                  │        W ~ S/(1−ρ)    (the knee)
  └──────────────────────────────────────────────────┘
     ▲ where the service centers are:                    when λ > c/S:
     │ event loop (ex. 4) · thread pool 40 (ex. 5)           the queue grows by λ − c/S
     │ semaphore/connection pool (ex. 6) · processes (ex. 7) → limit + shedding (ex. 12)
     │ RPM/ITPM/OTPM limits, 429/529 (ex. 8)                 → do not multiply traffic with retries (ex. 9)
     │ task queue (ex. 14) · cache/batching (ex. 15–16)      → deadline, cancellation (ex. 10)
     │
  mixed traffic: S from 1 s to 300 s → variance → head-of-line (ex. 12) → separate pools / task queue
  you measure: trace (waiting vs service) · RED/USE metrics · profile only for CPU/blocking
```

Now read `01a-queueing-theory-in-practice.md`, and then start with exercise 1.
