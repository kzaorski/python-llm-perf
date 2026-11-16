# 08a. Reading: provider limits, retries, timeouts, fallback

A reading, not an exercise — no tasks and no definition of done. The goal is to understand
the mechanisms the application uses to defend itself against the LLM provider and to protect the
provider from itself — before Block III shows you an avalanche of 429s, a retry storm, requests
hanging for minutes, and a fallback that makes things worse. All of these mechanisms have a common
denominator: they **change the traffic that reaches the provider** and **how long a request holds
resources**. Every concept follows the same pattern:

> **Definition** → **Intuition/analogy** → **Why it matters** → **Common mistake**

Come back here when things stop adding up. Short definitions are in `glossary.md`.

---

## Provider limits: RPM, ITPM, OTPM

**Definition.** An LLM provider limits traffic **per organization / key** along
several dimensions at once, counted in a one-minute window:
- **RPM** — requests per minute,
- **ITPM** — input tokens per minute,
- **OTPM** — output tokens per minute.

The limits work like a **token bucket**: the bucket's capacity equals the limit and it refills
continuously; every request takes tokens out; when there are none left, you get a
**429** response (`anthropic.RateLimitError`) with a `retry-after` header (how many seconds to wait
before coming back). Every response carries the state of the buckets:
`anthropic-ratelimit-{requests,input-tokens,output-tokens,tokens}-{limit,remaining,reset}`.
A separate case is **529 overloaded** (`anthropic.OverloadedError` — in SDK 2.x it is
**not** a subclass of `InternalServerError`): your limit is fine, but the provider has no spare
capacity.

**Intuition.** A gym membership with a cap on visits and a cap on treadmill minutes per
hour (429: "you have used up your limit, come back in 2 minutes") — and, separately, the situation
where all the treadmills are taken by other people (529: "there is no room for anyone").

**Why it matters.** A limit is **capacity** in the queueing-theory sense: the mock's `limits` profile
has RPM 120, ITPM 60,000, OTPM 12,000. A summary generates 200 tokens,
so OTPM lets through 12,000 / 200 = **60 summaries/min = 1/s**, although RPM
would allow 2/s — the tightest dimension binds. Ex. 8: traffic of 3/s × 60 s
(180 requests against a capacity of ~60) → the mock returns **133 × 429**, and some requests end
in an error. After adding a client-side limiter: **0 × 429**, all 180 OK,
but the excess **waits on our side** (wait p99 58 s). The limiter does not create capacity;
it only moves the queue from the provider (where it shows up as errors
and retries) to the application (where you can measure it and bound it — ex. 12).

**Common mistake.** A limiter that counts only requests. The token dimension
changes with the length of the prompt and the response — a batch of 100 claims of ~80
tokens each is 8,000 input tokens in a single request; at an ITPM of 60,000 that fits
7.5 such batches per minute (reading 14a). A second mistake: a limiter that
waits for a "probe" — the limit headers from the first response. A non-streaming response
carries the headers only after the whole generation; with minute-long calls such a probe holds up
the start of the process for minutes (measured while building the course: +10 s in a test with a long
silence). The first wave should be held back by the slot pool, and the headers should only correct the pace.

---

## Retries: when and how

**Definition.** A **retry** is sending the same request again after a
transient error. Three decisions:
1. **What to retry** — transient errors: 429, 529, 5xx, a dropped connection. Do not
   retry: 400 (a malformed request — repeating it gives the same result), 401/403. A **timeout**
   is a special case: the provider usually keeps working on the previous
   attempt, so a repeat doubles its load and your time (this course does not retry
   timeouts).
2. **When** — **exponential backoff**: the pause grows with the attempt number
   (base · 2ⁿ, with an upper cap), with **jitter** — a random spread of the
   pause. **Full jitter**: pause ~ U(0, min(cap, base · 2ⁿ)). If the provider
   sent `retry-after`, it takes precedence.
3. **How many** — a limit on attempts per request **and** a global **retry budget**
   (retries as a fraction of all requests in a time window).

The `anthropic` SDK 2.3 has its own layer: by default **`max_retries=2`** (3 attempts),
pauses of 0.5–8 s, it honors `retry-after`, and it also retries timeouts of non-streaming
requests.

**Intuition.** You call a busy helpline. The sensible approach: wait, longer after each
attempt, and every caller a little differently. The foolish one: all
customers call back exactly 1 second after being disconnected — the switchboard
gets waves ever larger than the original traffic.

**Why it matters.** For a base of 0.5 s and a cap of 8 s (the ex. 9 solution), the pauses before successive
attempts are drawn from U(0, 0.5), U(0, 1), U(0, 2), U(0, 4) s… Clients that
got an error at the same moment come back spread out in time, not in a single wave.

**Common mistake.** Backoff without jitter ("exponential is enough"). Everyone
who failed together comes back together after 0.5 s, then together after 1 s — the overload
shifts in time but does not dissipate.

---

## Amplification and the retry storm

**Definition.** **Retry amplification** is the ratio of HTTP attempts sent to the
provider to requests that arrived at the application. Layers **multiply**: 3 application
attempts × 3 SDK attempts = up to **9** attempts per user request (and every
proxy or client above adds another factor). A **retry storm** is
a situation where an overloaded provider answers with errors, the retries increase the
traffic, so there are more errors — and the system can stay overloaded even after
the original cause is gone (a **metastable** state).

**Intuition.** A traffic jam at the entrance to a city in which every driver who
did not fit onto the roundabout circles the block and tries again — the traffic on the roundabout
consists mostly of the same cars, not new ones.

**Why it matters.** Ex. 9, `overload` profile (capacity of 8 generations + a queue of 8,
anything above gets 529), traffic of 10/s × 20 s:
- two layers of retries without jitter: **3.65 HTTP attempts per request** (730 attempts,
  567 × 529), 163 successes;
- one layer (SDK `max_retries=0`), full jitter, a 20% budget: **1.20 attempts
  per request** (88 × 529), 152 successes.

The number of successes is almost the same — uncontrolled retries **do not save requests**;
they just load the provider three times over (and cost three times the input). A 20%
budget sets a ceiling on amplification: 1 + 0.2 = 1.2 — which is exactly what was measured.

**Common mistake.** Retries in several layers, "because every one should be
resilient". Pick **one** layer that retries (with a budget and jitter) and explicitly turn retries
off in the others — for the SDK, `max_retries=0`. A second one:
a fallback that retries a 529 at the second provider — overload is not an outage;
it moves the storm to the backup provider.

---

## Timeouts: connect, read, write, pool — and what they do not measure

**Definition.** An HTTP client (httpx2, and through it the SDK) has four separate
timeouts, all **per operation**:
- **connect** — establishing the TCP/TLS connection,
- **read** — waiting for the **next chunk of data** from the socket (that is, an **idle**
  limit, not a limit on the whole: every received byte resets the clock),
- **write** — sending a chunk of data,
- **pool** — waiting for a free connection in the pool.

Defaults in the `anthropic` SDK 2.3: connect 5 s, read / write / pool **600 s**.
**None of them is a total limit.** The total limit — the
**deadline** — you build in the application: `asyncio.timeout(seconds)` around the whole
call (including retries); after it expires the task is cancelled.

What "read" means in practice depends on the mode:
- **non-streaming** — the response arrives in full after the generation ends,
  so read has to cover **TTFT + the entire generation**;
- **streaming** — read has to cover the **longest gap between
  events** (including the silence before the first token).

**Intuition.** A read timeout means "hang up if the other party is silent for more than
30 s", not "hang up after 30 s of conversation". The conversation can last an hour if
the other party keeps saying something.

**Why it matters.** Measurements from building the course (mock, SDK with `timeout=30`):
- a stream of 150 s of generation with a short TTFT — **completes correctly after 148.9 s**:
  a read of 30 s did not interrupt the 150-second call;
- the same with `asyncio.timeout(60)` — aborted after **60.0 s**, and the mock records a
  cancelled generation (the provider-side slot is freed);
- non-streaming, 90 s of silence — `APITimeoutError` only after **91.3 s**: the SDK
  retried twice (3 × 30 s), leaving 3 abandoned generations at the provider;
- a stream with a 40 s pause in the middle — **`httpx2.ReadTimeout` after 30.5 s**.

In ex. 10 the skeleton has the default 600 s: the provider is silent for 120 s, traffic of 2/s × 30 s →
32 / 32 slots busy, 28 waiting, the last response after **254 s**. With a read of 15 s for
short requests: 504 after 15–25 s, the last one after 44.5 s, 59 generations aborted.

**Common mistake.** `except anthropic.APITimeoutError` as "timeout handling". A timeout
**in the middle of a stream** surfaces as a **raw
`httpx2.ReadTimeout`** — it is not a subclass of `APITimeoutError` and the SDK does not retry it. The other way around:
`except anthropic.APIConnectionError` also catches `APITimeoutError` (a subclass)
and `PoolTimeout` — so the "dropped connection" branch suddenly handles timeouts too.

---

## Silence before the first token, and ping

**Definition.** With a long TTFT (60–180 s in this course), no data
flows for minutes. The provider can counteract this: send the **response headers
right away** and, every so often, an SSE **`ping`** event (in the mock, every 15 s). Every
ping resets the client's read timeout and the idle timeouts of intermediaries
(proxy, load balancer).

**Intuition.** The other party says "still checking…" every 15 seconds — you
do not hang up, even though there is still no answer.

**Why it matters.** A stream with 90 s of silence at a read of 30 s: without pings,
`httpx2.ReadTimeout` after 30.0 s; with a ping every 15 s — completes correctly after 90.1 s. In ex.
10 (4 analyses: 90 s of silence + 30 s of generation) the non-streaming skeleton with a read of
60 s and 2 SDK retries gives a 504 after **181.6–191.6 s** (3 × 60 s) and **10
abandoned generations**; after switching to a stream (ping 15 s < read 60 s,
`max_retries=0`): 4 × 200 after **122.0 s**, 0 abandoned. So you set the read timeout
to ≥ 2 × the longest expected silence **or** ≥ 2 × the ping interval, if
the provider sends pings.

**Common mistake.** "The application sees the pings, so it can measure progress with them."
The SDK's `MessageStream` iterator **does not yield** `ping` events (measured: the ping
counter on the application side = 0) — they keep the connection alive at the HTTP level, but
the application code never receives them.

---

## The timeout budget across layers

**Definition.** There are several clocks on a request's path: the load generator (k6),
the proxy / process manager (gunicorn), the application deadline, the SDK timeouts. A consistent
**timeout budget** is how they nest from the inside out:
**SDK timeouts (idle) < application deadline (per class) < timeout of
the outer layers (proxy, k6)**. Then the application decides when to
abort — with a clear error (504 `deadline_exceeded`) and with resources released.

**Intuition.** Matryoshka dolls: every outer one has to be bigger than the inner one,
or they will not close. If the outer one (k6) is smaller, it "closes" on
unfinished work while the inner one (the application) still holds the slot.

**Why it matters.** Pitfalls measured while building the course:
- **k6** — the default request timeout is **60 s**: a 90-second call ends
  with `status 0` / `request timeout` after 60.0 s and invalidates a minute-long test.
  The course scripts set `timeout` explicitly (e.g. 400 s with a long-class deadline of
  330 s) and a `gracefulStop` longer than the longest request;
- **gunicorn `-k sync`** — the default `--timeout 30` kills a worker on a 45 s and a
  90 s call (500 + `WORKER TIMEOUT`); with UvicornWorker a 90 s request
  ends with a 200;
- **a per-class deadline** in the application (the ex. 10 solution): 30 s for short,
  330 s for long (a 300 s tail + headroom for the provider-side queue).

**Common mistake.** "Let's raise all the timeouts to 10 minutes." Then none of them
works as a signal: a hung provider holds slots for 10 minutes
(ex. 10: the last response after 254 s at 2 requests/s), and a test with a timeout that is too
short only shows the diagnostic symptom once the timeout is
deliberately matched to the class. A deliberately short timeout should produce a clear error, not
an accidental invalidation of the test.

---

## Fallback to a second provider

**Definition.** **Fallback** — when the primary provider (`a`) fails, the application
sends the request to the backup (`b`; in the mock a separate endpoint with separate
limits). The key decision: what counts as an **outage** (a dropped connection, a 5xx,
a timeout) and what counts as **overload** (529, 429), which a fallback will merely move elsewhere.

**Intuition.** A backup courier: if the first one did not show up, you call the
second. But if every time you first wait an hour for the first one —
the package still goes out an hour late.

**Why it matters.** Ex. 11: `a` is silent for 30 s, read timeout 15 s, traffic of 2/s × 40 s. Without
extra logic **every** request pays 15 s at `a` plus the call to `b`:
p50 **19.8 s**, and `a` receives 80 / 80. The fallback works — but the latency
is set by the dead provider's timeout, and its slots (and ours) are tied up
waiting for nothing.

**Common mistake.** A "silent" fallback. In ex. 6 (connection pool too small,
`PoolTimeout` surfacing as `APITimeoutError`) the fallback pushed 77 / 300
requests over to `b` — a local problem looked like a healthy system. Every fallback has to
leave a trace: a span attribute, a counter per provider.

---

## Circuit breaker

**Definition.** A **circuit breaker** is a state machine placed in front of an unreliable
dependency:
- **closed** — traffic flows normally, and the breaker counts consecutive failures;
- **open** — after *N* consecutive failures, for a time *T* requests do not
  go to `a` at all (straight to the fallback or a fast error);
- **half-open** — after time *T* it lets **one** probe request through; success
  closes the breaker, failure opens it again.

In the ex. 11 solution: N = 5, T = 30 s, the state visible as the `llm.cb.state` attribute
on the `llm.call` span. A 529 does not count as a failure.

**Intuition.** A fuse in a flat: after a short circuit it cuts the circuit so as not to
burn the wiring; after a while someone tries to switch one circuit on — if it holds,
the rest come back.

**Why it matters.** The same scenario with a breaker: p50 **7.7 s** (instead of 19.8 s),
`a` receives **33 / 80** — the breaker opened after 5 failures, but ~30
requests were already in flight to `a` and paid the timeout anyway. The breaker shortens
the duration of the incident for new requests and gives the provider time to get
back on its feet without our traffic.

**Common mistake.** A half-open state that lets all the traffic through at once — if
`a` has not recovered yet, all the requests pay the timeout again, and if it has barely
recovered — the wave knocks it down again. A second one: a breaker that counts 429/529 as failures — it will cut
off the road to a healthy, merely overloaded provider and move the traffic to a place that
has a limit too.

---

## How it all fits together (map)

```
 request ──► per-class application deadline (asyncio.timeout: 30 s / 330 s)     [ex. 10]
               │  (the k6 timeout and gunicorn MUST be longer; sync 30 s kills)  [ex. 7, 10]
               ▼
            rate limiter (RPM / ITPM / OTPM from headers; 429 → pause)           [ex. 8]
               ▼
            ONE retry layer: backoff + full jitter + retry-after + 20% budget    [ex. 9]
               │  (SDK max_retries=0; timeouts are not retried)
               ▼
            breaker a: closed → (5 failures) → open 30 s → half-open (1 probe)   [ex. 11]
               ├──► provider a ── read = idle (stream: ping 15 s), 529 ≠ outage
               └──► provider b (fallback, trace in the span and metrics)
 amplification = HTTP attempts / requests: 3.65 uncontrolled, 1.20 with the budget
```

Now go on to ex. 8.
