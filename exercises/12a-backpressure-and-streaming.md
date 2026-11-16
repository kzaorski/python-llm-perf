# 12a. Reading: backpressure, load shedding and streaming

A reading, not an exercise — no tasks and no definition of done. The goal is to understand what a
system should do **when the arrival rate exceeds capacity** — and why "let them wait" is the worst
possible answer when calls last minutes. The second part covers response streaming (SSE), that is,
how to measure what the user actually feels — the time to the first chunk. Every concept follows the
same pattern:

> **Definition** → **Intuition/analogy** → **Why it matters** → **Common mistake**

Come back here when things stop adding up. Short definitions are in `glossary.md`.

---

## Backpressure

**Definition.** **Backpressure** is the mechanism by which an overloaded service center **signals the
sender** to slow down. When λ > X_max (00-theory), the system has only three options:
1. **Queue without a limit** — accept everything; the waiting time grows without end, and so does
   memory (this is the *absence* of backpressure).
2. **Block the sender** — do not accept a new request until there is room (backpressure "upstream":
   a full socket backlog, a closed workload model).
3. **Reject the excess** (*load shedding*) — quickly refuse some requests so the rest are served in a
   reasonable time.

With HTTP clients outside your control, the real choice is between 1 and 3.

**Intuition.** A club with a bouncer. Without one, everybody gets in, nobody can breathe inside, and
nobody gets a drink. With a bouncer, some people hear at the door "we're full, come back in 20
minutes" — and the people inside have a normal evening.

**Why it matters.** A queue without a limit does not add capacity — it only changes **who** waits and
**for how long**. With minute-long calls this turns into wasted work: the client gives up after a few
minutes, and the system either still processes the request or abandons it halfway. A rejection after
1 ms is a better answer for the client (and for you) than a 504 after 6 minutes.

**Common mistake.** "A queue is a buffer — it will smooth out the peak." It smooths a **short** peak,
when the average λ < X_max. Under sustained overload the queue only postpones the failure and adds
latency for everyone, including those who could have been served.

---

## The bounded queue and its size

**Definition.** A **bounded queue** has a maximum length *K*; a request that arrives at a full queue
is refused immediately. *K* follows from Little's law: a request at the back of the queue waits about
**K / X_max**, so **K ≈ acceptable wait × X_max**.

**Intuition.** A waiting room with a fixed number of chairs. If you know the doctor sees 4 people an
hour and nobody wants to wait more than 2 hours, you put out 8 chairs.

**Why it matters.** The ex. 12 solution has queues of 64 (short) and 8 (long):
- short: 64 / 30 per s ≈ **2.1 s** of waiting at the back of the queue with a capacity of 32 slots
  (30/s);
- long: 8 / 0.105 per s ≈ **76 s** with 16 slots for analyses lasting ~153 s (16 / 153 ≈ 0.105/s).

For long calls, half a minute in the queue does not matter next to several minutes of service; for
short ones, 2 s is already a lot. The queue size is an SLO decision, not a memory decision.

**Common mistake.** A queue length limit without a **time** limit on waiting. A queue of 8 may never
overflow, and yet requests wait a long time because all the slots are held by multi-minute calls.
That is why, next to the length, there is a **wait budget** (below).

---

## Load shedding: 503, Retry-After and the wait budget

**Definition.** A refusal should be **fast and readable**: status **503 Service Unavailable** (or 429
when the limit applies to a specific client) with a **`Retry-After`** header — after how many seconds
it is worth trying again. In the ex. 12 solution the refusal happens in two places:
- **at the door** — the class queue is full (`queue_full`), `Retry-After` = the class wait budget;
- **after the wait budget** — a request that did not get a slot within 5 s (short) / 20 s (long) is
  pulled from the queue with a 503 instead of waiting any longer.

The `rejected` outcome is counted separately in `app_requests_total{outcome}`.

**Intuition.** "Please call back in 20 minutes" beats keeping the caller on the line for an hour with
hold music — the caller knows what to do, and the line is free for someone who can be served now.

**Why it matters.** Ex. 12, mixed traffic for 180 s (short 4/s, long 0.4/s), separate pools 32 / 16
already fixed (variant C → B):
- **no queue limit and no budget (C)**: long calls wait p50 88 s / p99 272 s, at t = 180 s there are 46
  long calls waiting (the oldest 115 s), **30 clients abandon the request** after 400 s (the k6
  timeout) — 30 generations cancelled after minutes of work; drain 402 s;
- **with a queue of 8 and a 20 s budget (B)**: **42 fast 503s**, long-call wait p99 19.4 s, 8 waiting
  at t = 180 s, drain 213 s.

The number of completed long calls dropped (43 → 30) — and that is **correct**: the capacity for long
calls (~0.1/s) is four times smaller than the arrival rate (0.4/s). Without rejection the system
would not have done more anyway; it would only have stretched the wait for everyone and wasted work
on abandoned requests. Ultimately, long calls should go to a task queue (reading 14a).

**Common mistake.** A client that answers a 503 with an immediate retry — the rejection turns into a
retry storm (reading 08a). `Retry-After` works only if clients honor it; for your own clients (other
services, workers) that is an obligation. A second mistake: measuring rejections in a way that
inflates errors — a fast 503 is **healthy** behavior under overload, not a failure; report it
separately from 504 and 5xx.

---

## The deadline and its propagation

**Definition.** A **deadline** is an absolute point in time after which the result is no longer worth
anything to the client. Unlike a timeout (how long to wait for a single operation), a deadline covers
**the whole**: the wait in the queue, the call, the retries. **Deadline propagation** — every layer
knows how much time is left and:
- does not start work that will not finish in time (for example, it does not call the LLM if the
  request has already spent most of its budget in the queue),
- passes the remaining time on (to downstream calls, as a timeout).

**Intuition.** The train leaves at 6:00 PM. If at 5:55 PM you are standing in line at the ticket
window and the sale takes 10 minutes, there is no point in staying in line. A clerk who knows when
your train leaves will send you away right now.

**Why it matters.** In the course, the wait budget (ex. 12: 5 s / 20 s) and the call deadline (ex. 10:
short 30 s, long 330 s, `asyncio.timeout`) are two parts of the same request budget. Without them, a
request can wait minutes in the queue and then still occupy a slot at the provider for more minutes —
for a client that disconnected long ago.

**Common mistake.** One shared deadline for all classes. 150 s "saves" the short calls but kills every
analysis that takes 200 s (a test run while building the course: 7 / 7 long streams exceeded their
deadline). The deadline must match the request **class**.

---

## Cancellation on disconnect and releasing the slot

**Definition.** When the client disconnects (closes the tab, a k6 timeout, a proxy drops the
connection), the server should **cancel** the work being done for it: the asyncio task gets
`CancelledError`, the connection to the provider is closed, the provider stops generating, and the
semaphore slot and the provider slot are released right away. The server learns about the disconnect
through ASGI (the `http.disconnect` event, in Starlette `await request.is_disconnected()`).

Two pitfalls measured while building the course:
- **Starlette 1.10 with ASGI spec ≥ 2.4 does not listen for disconnects in `StreamingResponse`** —
  the application has to check `request.is_disconnected()` itself (in the course: a guard every 0.5 s
  next to the LLM call, a check every few chunks in a stream);
- **`@app.middleware("http")` (BaseHTTPMiddleware) breaks `request.is_disconnected()`** in handlers —
  with it, cancellation did not work at all (6 / 6 generations finished as wasted work). The course
  application's middleware is written as pure ASGI.

**Intuition.** A restaurant guest left before the dish was served. A good kitchen stops cooking and
gives the table to the next party; a bad one cooks to the end, and the table sits occupied with a
plate for nobody.

**Why it matters.** With minute-long calls, this is a difference of minutes on every abandoned
request. Ex. 10: 6 analyses with 150 s of generation, the client gives up after 20 s:
- without cancellation: the provider keeps generating, slots free up only **172.9 s** after the
  disconnect, 18 abandoned generations (each 3 ×, because the SDK retried the timeouts);
- with cancellation: slots free up after **0.7 s**, 6 generations cancelled.

In the final (4 flaws at once), the missing cancellation shows up as `mock_llm_cancelled_total` = 0
with abandoning clients and a drain of **125 s** after the end of traffic (with cancellation: 24
cancelled, drain 32 s).

**Common mistake.** "The client disconnected, so the server stopped working." By default it did not:
the coroutine keeps waiting for the provider and the provider keeps generating. How to check: after
interrupting a test, `llm_inflight` and `mock_llm_generating` must fall to zero within seconds, and
`mock_llm_cancelled_total` must rise.

---

## SSE streaming

**Definition.** **Server-Sent Events** (SSE) is a stream of text events within a single HTTP response
(`Content-Type: text/event-stream`): each event is a set of `event: …` and `data: …` lines ended by a
blank line. The LLM provider uses it to send a response in pieces as it is generated (events for the
message start, content chunks, `ping`, the end). The course application passes the stream on to the
client (`/reply/stream`: `delta` events with text chunks and `end` with the timings).

**Intuition.** A live broadcast of a match instead of a recording released after the final whistle —
the viewer sees the action from the first minute, even though the match lasts just as long.

**Why it matters.** Three benefits, each important under load:
1. **Perceived time** — the user sees the first words after the TTFT (~0.5 s), not after the whole
   generation (a few seconds — or minutes).
2. **Timeout semantics** — the read timeout watches the gaps between events, not the whole response
   (reading 08a); a multi-minute response does not need a 10-minute read timeout.
3. **Early disconnect detection** — with every chunk you can check whether the client is still on the
   other end.

**Common mistake.** "Streaming is faster." The total time is the same (TTFT + tokens / speed); what
changes is the time to the **first** chunk and how the system reacts to silence and disconnects.

---

## Server TTFT vs client TTFT, and buffering

**Definition.** On the stream path there are at least three different "times to the first token":
- **TTFT at the provider / on the application side** — from sending the request to the first chunk
  from the provider (`llm_ttft_seconds`);
- **the first chunk sent to the client** — from the application accepting the request to sending the
  first `delta` (`app_stream_first_chunk_seconds`);
- **client TTFT** — from sending the request to receiving the first chunk (measured on the client
  side, in the course by `scripts/stream_ttft.py`).

**Stream buffering** is a situation where someone along the way collects the chunks and sends them
only at the end (or in large portions): an application that assembles the whole text before the
first `yield`, a compression layer, a proxy that buffers responses. The provider's TTFT is then fine,
and the client still waits for everything.

**Intuition.** A parcel sent by express that sits in the sorting center until the end of the day
because the courier only delivers with a full truck. The sender sent it fast, the recipient received
it late — each measures something different.

**Why it matters.** Ex. 13: 20 streams, 5 at a time — with buffering the first chunk at the client is
p50 **2.19 s = 100%** of the total, after the fix (`yield` of every chunk) **0.55 s = 19%** of the
total (2.89 s). In the final: the first chunk to the client p50 **8.07 s** with a provider TTFT of
0.63 s — the difference is an unambiguous sign of buffering (without the flaw: 0.48 s vs 0.48 s).

**Common mistake.** Trusting the timing metric from the load generator. In k6, `http_req_waiting` with
SSE is the time **to the headers** — and `StreamingResponse` sends the headers right away, before the
first chunk exists. Buffering is invisible to that metric. Compare `app_stream_first_chunk_seconds`
with `llm_ttft_seconds`, or measure with a client that reads the stream.

---

## How it all fits together (map)

```
 arrival ──► bounded queue per class (64 / 8)  ── full ──► 503 + Retry-After (fast)          [ex. 12]
                 │ wait budget (5 s / 20 s)    ── exceeded ──► 503
                 ▼
              slot (separate pools 32 / 16) ──► deadline per class (30 s / 330 s)             [ex. 10]
                 │                              └─ disconnect guard ──► cancel: slot returns in < 1 s
                 ▼                                 (Starlette: call is_disconnected() yourself; no BaseHTTPMiddleware)
              SSE stream from the provider ── provider TTFT (llm_ttft_seconds)
                 ▼   yield every chunk (no buffering)                                         [ex. 13]
              client ── first chunk (app_stream_first_chunk_seconds, stream_ttft.py)
                        k6 http_req_waiting = headers → does NOT see buffering
 K ≈ acceptable wait × X_max;  sustained excess → reject, or move to a task queue (reading 14a)
```

Now move on to ex. 12.
