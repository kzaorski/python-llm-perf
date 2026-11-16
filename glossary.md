# Glossary — python-llm-perf course

An alphabetical glossary of the terms used in `exercises/00-theory.md`, the block readings (`01a`, `04a`,
`08a`, `12a`, `14a`) and the exercises. Each entry has a short definition, a pointer to where the concept is
explained in depth (`→ 00`, `→ 01a`…) and to the exercises where you use it (`→ ex. N`). The full
explanations (definition → intuition → why it matters → common mistake) are in the theory documents — this is
only a quick cheat sheet.

Exercise map: ex. 1–3 = measurement and queueing theory (trace, open/closed model, Little's law and the
knee), ex. 4–7 = asyncio, pools, processes, ex. 8–11 = the provider (limits, retries, timeouts, fallback),
ex. 12–13 = backpressure and streaming, ex. 14–17 = task queue, cache, batching, comparison with the real
Claude, ex. 18 = the final.

---

**429 (Too Many Requests)** — the provider's response after you exceed an RPM / ITPM / OTPM limit; in the SDK
`anthropic.RateLimitError`, with a `retry-after` header.
→ 00, 08a, ex. 8.

**503 + Retry-After** — a fast refusal *from the application* when the queue is full or the wait budget is
exceeded; `Retry-After` tells the client when to come back. Healthy behavior under overload, reported
separately from errors. → 12a, ex. 12.

**529 (overloaded)** — the provider has no spare capacity (regardless of your limit); in SDK 2.x
`anthropic.OverloadedError`, which is **not** a subclass of `InternalServerError`. Overload, not an outage —
a fallback should not retry it. → 00, 08a, ex. 9, 11, 14.

**Age of the oldest** — how long the oldest request / task has been waiting
(`llm_oldest_waiting_age_seconds`, `queue_oldest_age_seconds`, `mock_llm_oldest_inflight_seconds`); the best
signal for a queue SLO. → 00, 14a, ex. 12, 14.

**anyio thread limiter** — the default limit of 40 concurrent threads for `def` handlers and
`run_in_threadpool` in FastAPI; above the limit, calls wait in waves of 40, with no CPU use and no span.
→ 04a, ex. 5.

**Arrival rate (λ)** — the intensity at which requests arrive; in an overloaded system it is higher than
throughput, and the difference goes into the queue. The traffic phase is called the *inflow*. → 00, ex. 2, 3.

**`asyncio.timeout`** — a context manager with a total limit for a block of code; when exceeded it cancels the
task and raises `TimeoutError`. In the course it serves as the deadline of an LLM call. → 08a, ex. 10.

**Backlog** — the number of requests waiting and in progress at the moment the inflow ends; reported together
with the age of the oldest and the drain time. → 00, ex. 12, 18.

**Backoff, exponential** — a pause before a retry that grows with the attempt number (base · 2ⁿ, with an
upper cap); without jitter, clients come back together. → 08a, ex. 9.

**Backpressure** — a signal from an overloaded service center to the sender to slow down; in HTTP, in
practice: a bounded queue and load shedding. → 12a, ex. 12.

**BaseHTTPMiddleware** — the class behind `@app.middleware("http")` in Starlette/FastAPI; it breaks
`request.is_disconnected()` in handlers, so cancellation on disconnect stops working. The course middleware is
pure ASGI. → 12a, ex. 10.

**Batching** — gluing many requests into one LLM call; parameters: window and maximum size, batch ≈
min(λ · window, max), latency + ≤ window. It reduces the number of requests, not tokens. → 14a, ex. 16.

**Bottleneck** — the service center with the smallest capacity on the path; only widening it increases
throughput. → 01a, ex. 6, 8.

**Bounded queue** — a queue with a maximum length K; the excess is refused immediately. K ≈ acceptable wait ×
capacity. → 12a, ex. 12.

**Bulkhead (separate pools)** — splitting slots between request classes (in the course 32 short / 16 long) so
that one class cannot take the other's resources; the cure for head-of-line blocking. → 01a, ex. 12.

**Cache stampede** — after a key expires, N concurrent misses call the LLM N times; the cure: single-flight.
Measured: 50 questions → 50 calls. → 14a, ex. 15, 18.

**Cancellation** — interrupting an asyncio task (`task.cancel()` → `CancelledError` at the point of waiting);
the only way to make a waiting call give back its semaphore slot, its connection and its generation at the
provider. → 04a, 12a, ex. 10, 18.

**`CancelledError`** — the exception a cancelled task receives at its `await`; it inherits from
`BaseException`, so `except Exception` does not catch it (and should not). → 04a, ex. 10.

**Capacity (X_max)** — the largest sustainable throughput of a service center: c / S; the capacity of a path
= the minimum over its service centers. → 00, 01a, ex. 3.

**Capacity planning** — c = ⌈λ_peak · S / ρ_target⌉ with ρ_target 0.7–0.8, plus a check of the ceilings
(provider limits and capacity) that you cannot raise with slots. → 01a, ex. 3, 6.

**Circuit breaker** — a state machine in front of an unreliable provider: closed → (N failures) → open for T →
half-open (one probe request) → closed or open again. In the course N = 5, T = 30 s. → 08a, ex. 11.

**Closed model** — a fixed number of users waiting for a response (k6 `constant-vus`); X = N / (R + Z), it
slows itself down under load. → 00, ex. 2.

**Concurrency (L)** — the number of requests in the system at once (waiting and being served). → 00, ex. 3.

**Connection pool** — the set of TCP connections of an HTTP client (`max_connections`,
`max_keepalive_connections`); smaller than the semaphore, it creates a hidden queue. → 04a, ex. 6.

**Coordinated omission** — a measurement error of the closed model: the generator waits for the slow system,
so it does not measure the requests that would wait in the queue in real traffic. Measured: p99 1.57 s
(closed) vs 4.41 s (open). → 00, ex. 2.

**Deadline** — an absolute time limit for the whole request (wait + call + retries), after which the result
loses its value; in the course per class: 30 s / 330 s. → 08a, 12a, ex. 10, 12.

**Disconnect guard** — a task running next to the LLM call that checks `request.is_disconnected()` (in the
course every 0.5 s); after a disconnect it cancels the call. → 12a, ex. 10.

**Drain** — the time from the end of the inflow to empty queues; ≈ backlog / capacity. For multi-minute calls
it is counted in minutes (ex. 12: 213–402 s). → 00, 01a, ex. 12, 18.

**`dropped_iterations`** — a k6 counter in the open model: requests the generator did not manage to send on
time (no VU available); nonzero = invalid measurement. → 00, ex. 2, 3.

**Erlang C (M/M/c)** — a queue model with c servers and a shared queue; the Erlang C formula gives the
probability of waiting. More servers = the knee moves closer to ρ = 1 and gets sharper. → 00, 01a, ex. 3.

**Event loop** — the single asyncio thread that wakes the coroutines that are ready to run; for the code
between `await`s it is a service center with one server. → 04a, ex. 4.

**Event loop lag** — the delay with which the loop runs a scheduled callback; seconds = blocked loop
(`app_event_loop_lag_seconds`, `/diag`). → 04a, ex. 4.

**Fallback** — switching to a backup provider when the primary fails; without a circuit breaker every request
pays the timeout of the dead provider (measured p50 19.8 s). → 08a, ex. 11.

**GIL** — CPython's global interpreter lock: only one thread executes Python code at a time; waiting on I/O
releases it. → 04a, ex. 4, 5.

**`gracefulStop` (k6)** — how long k6 waits for in-flight requests after the scenario ends (30 s by default);
shorter than the longest request, it cuts multi-minute calls and falsifies the drain. → 00, ex. 10, 12.

**gunicorn** — a process manager; `-k sync` = one request per process and the default `--timeout 30` that
kills the worker, `-k uvicorn_worker.UvicornWorker` = an asyncio loop in every process. → 04a, ex. 7.

**Head-of-line blocking** — short requests wait behind long ones in a shared queue and pool; measured: short
requests wait p50 29 s with a service time of ~1 s. → 01a, ex. 12.

**Histogram** — a metric with value buckets; you compute percentiles from it (`histogram_quantile`). The
buckets must reach the longest times (up to 300 s for the mock). → 00, ex. 1, 3.

**`http_req_waiting` (k6)** — time to the first byte of the response; for SSE = time to the headers, so it
does not see stream buffering. → 12a, ex. 13.

**httpx2** — the HTTP client underneath the `anthropic` 2.x SDK; the `HTTPX2ClientInstrumentor`
instrumentation produces a `POST` span per HTTP attempt. Default `Limits` 100 / 20, in the SDK
`max_connections=1000`. → 04a, ex. 1, 6.

**ITPM** — the input tokens per minute limit; most easily exceeded with large batches and long prompts.
→ 00, 08a, 14a, ex. 8, 16.

**Jitter** — random spreading of the pause before a retry; full jitter: U(0, min(cap, base · 2ⁿ)). It breaks
up synchronized waves of retries. → 08a, ex. 9.

**Knee of the curve** — the utilization region where waiting time starts to grow faster than load; for 32
slots measured at about 28–30/s. → 00, 01a, ex. 3.

**Latency (R)** — the response time of a single request = waiting + service; measured on the client and on the
server side (these are different numbers). → 00.

**Little's law** — L = λ · W for every stable system and every service center; hence the capacity c / S, the
pool size λ · S and the measurement consistency check. → 00, 01a, ex. 3, 6, 7, 14.

**`llm.queue_wait`** — the span of waiting for the LLM semaphore, a sibling of the `llm.call` span (not its
parent); plus the `llm.queue.wait_ms` attribute on the request span. → 00, ex. 1.

**Load shedding** — deliberately and quickly rejecting part of the traffic under overload so that the rest is
served in a reasonable time. → 12a, ex. 12.

**`max_retries` (SDK)** — the number of `anthropic` SDK retries, 2 by default (3 attempts), with pauses of
0.5–8 s and honoring of `retry-after`; set it to 0 when you have your own retry layer. → 08a, ex. 9, 10.

**Metastability** — a state in which the system stays overloaded after the cause is gone, because it generates
the excess itself (for example through retries). → 08a, ex. 9.

**M/M/1** — the simplest queue model (Poisson arrivals, exponential service, one server); W = S / (1 − ρ): at
ρ = 0.9 the time in system is 10 × S. → 00, ex. 3.

**Mock LLM** — your own server compatible with the Messages API (port 8061) with repeatable profiles: delays,
limits, 429/529, streaming, ping, multi-minute calls; two "providers", `a` and `b`. → 00, ex. 1, 8–14, 17.

**Multi-minute call** — an LLM call lasting 60–300 s (long TTFT, long stream, pauses); it occupies slots for
minutes and multiplies the cost of every timeout error and retry. → 00, 01a, 08a, ex. 10, 12.

**Network of queues** — a model of a system as service centers connected by flows of requests; the capacity of
the path is set by its bottleneck. → 00, ex. 4.

**Open model** — the generator sends at a set rate regardless of responses (k6 `constant-arrival-rate`,
`ramping-arrival-rate`); it shows queues the way real traffic does. → 00, ex. 2, 3.

**OTPM** — the output tokens per minute limit; the mock's `limits` profile: 12,000 → 60 summaries of 200
tokens per minute. → 00, 08a, ex. 8.

**Pending** — entries delivered to a worker but not acknowledged (`XPENDING`): in progress + prefetched;
healthy ≈ the worker's concurrency. → 14a, ex. 14.

**Percentile** — the value below which p% of measurements lie (p50, p99); you must not average percentiles
across instances. → 00, ex. 2, 3.

**Ping (SSE)** — an empty stream event sent by the provider (every 15 s in the mock); it resets the read
timeout during silence; the SDK's `MessageStream` iterator does not return it. → 08a, ex. 10.

**`PoolTimeout`** — exceeding the `pool` timeout while waiting for a connection in the httpx2 pool; in the SDK
it surfaces as `APITimeoutError` (a subclass of `APIConnectionError`). → 04a, ex. 6.

**Prefetch** — a worker pulling tasks in advance (taskiq-redis: `xread_count`); it hides the queue (lag = 0)
and hoards work in one process. → 14a, ex. 14.

**Profile, CPU vs wall-clock** — a CPU profile samples the threads that are computing, a wall-clock profile
samples all of them (including those waiting in a blocking call). Neither sees a suspended coroutine.
→ 00, ex. 4.

**Queue lag** — the number of stream entries not yet delivered to the consumer group (`XINFO GROUPS`); the true
length of the task queue (`queue_lag`). → 14a, ex. 14.

**Rate limiter** — a client-side limit matched to the provider's limits (from the `anthropic-ratelimit-*`
headers); it turns a 429 into waiting on our side. → 08a, ex. 8.

**Read timeout** — a limit on read **inactivity** (every byte resets the clock), not a total limit: a 150 s
stream with a 30 s read timeout finishes correctly. → 08a, ex. 10.

**`ReadTimeout` (httpx2)** — the read timeout exception; during a stream the SDK lets it out **raw** (not as
`APITimeoutError`) and does not retry. → 08a, ex. 10.

**RED** — service metrics: Rate, Errors, Duration. → 00, ex. 1, 18.

**Redis Streams** — a log of entries with consumer groups (`XADD`, `XREADGROUP`, `XACK`, `XINFO GROUPS`,
`XPENDING`); the task queue broker in the course. → 14a, ex. 14.

**Request class** — the category of a request by expected duration (`short` / `long`); slots, queues, wait
budgets and deadlines are set per class, and results are reported per class. → 00, ex. 12.

**Response cache** — an LLM result stored under a key for a TTL (in the course the FAQ in Redis); a hit does
not call the provider: λ_provider = (1 − h) · λ. → 14a, ex. 15.

**Retry amplification** — the ratio of HTTP attempts to the provider to user requests; the layers multiply (3
application attempts × 3 SDK attempts = up to 9). Measured: 3.65 uncontrolled, 1.20 with a 20% budget.
→ 08a, ex. 9.

**Retry budget** — a global limit on retries as a fraction of requests in a window (in the course 20% / 10 s);
it caps amplification at ×1.2 during a mass outage. → 08a, ex. 9.

**`retry-after`** — a header with the number of seconds until the next attempt; from the provider (429/529) it
takes precedence over your own backoff, from the application (503) it binds your clients. → 08a, 12a, ex. 8, 9,
12.

**RPM** — the requests per minute limit at the provider. → 00, 08a, ex. 8.

**Semaphore** — `asyncio.Semaphore(n)`: an explicit concurrency limit with a queue of waiters; in the course,
LLM slots per class with a measured wait time. → 04a, ex. 1, 6, 12.

**Server-Timing** — an application response header with the wait time and the LLM call time; k6 computes the
`app_*` trends from it (for example the wait of short requests). → ex. 2, 12.

**Service center** — a place in the system where requests wait for a resource and are then served (a slot, a
connection, a thread, the event loop); the unit of the network-of-queues model. → 00, 01a, 04a, 12a.

**Service time (S)** — the time during which a resource actually works for a request (here: the LLM call); the
basis of the capacity calculation X_max = c / S. → 00, 01a, ex. 1, 3.

**Single-flight** — on a cache miss only the first request computes, the rest wait for its result (an
`asyncio.Future` within a process, `SET NX PX` in Redis across processes). → 14a, ex. 15.

**SLO (service level objective)** — a measurable target for a service, for example a latency percentile that
must stay below a threshold; the age of the oldest waiting request is its best early signal.
→ 00, 12a, ex. 12, 18.

**Slot** — one place in a concurrency limit (semaphore, pool); held for the whole service time — for
multi-minute calls, for minutes. → 00, ex. 6, 12.

**Socket backlog** — the kernel queue of connections waiting for `accept()`; when it overflows, the client gets
a dropped connection. Under `gunicorn -k sync` the excess traffic waits there. → 04a, ex. 7.

**Span** — a segment of a trace with a start, an end, attributes and a parent; gaps between spans are time
nobody recorded. → 00, ex. 1.

**SSE (Server-Sent Events)** — a stream of text events in a single HTTP response (`text/event-stream`); this is
how the provider and the application send a response in pieces. → 12a, ex. 13.

**Steady state** — a period in which the averages have stopped changing; it arrives after several W (for
analyses — after minutes); at λ > X_max it does not exist. → 01a, ex. 3, 12.

**Streaming, buffered** — something on the way collects the stream chunks and sends them at the end; the
provider's TTFT is fine, the client waits for everything (measured: 100% of the time vs 19%).
→ 12a, ex. 13, 18.

**Tail of the distribution** — the upper percentiles (p99, max); in an LLM application partly by design (the
class of multi-minute calls), which is why it is reported per class. → 00, ex. 2, 12.

**Task queue** — a broker (Redis Streams) between the producer (the application) and the worker; it shifts
work in time, it does not add capacity. → 14a, ex. 14.

**taskiq** — a task queue library with `async def` tasks; worker concurrency = `--workers` ×
`--max-async-tasks` (default 2 × 100). → 14a, ex. 14.

**Thread pool** — the threads that run synchronous code outside the loop; in FastAPI limited by the anyio
limiter (40). → 04a, ex. 5.

**Throughput (X)** — how many requests per second the system **completes**; report the achieved rate, not the
target rate. → 00, ex. 2, 4.

**Timeout budget** — arranging the clocks from the inside out: SDK timeouts (inactivity) < application
deadline (per class) < timeouts of the outer layers (proxy, k6). → 08a, ex. 10.

**Timeout, k6** — the default request time limit in k6: 60 s; multi-minute tests must set `params.timeout`
(otherwise `status 0` after 60 s). → 08a, ex. 10, 12.

**Token bucket** — a limit model: a bucket with capacity = the limit, constantly refilled; a request takes
tokens, no tokens = 429. → 08a, ex. 8.

**Tokens/s** — the generation speed after the first token (in reality ~225–300, the mock 250); total time ≈
TTFT + tokens / speed. → 00, ex. 17.

**Trace** — the tree of spans of a single request; it shows where the request spent its time, including
waiting. → 00, ex. 1.

**TTFT (time to first token)** — the time to the first chunk of the response; different at the provider
(`llm_ttft_seconds`), different as sent to the client (`app_stream_first_chunk_seconds`), different at the
client. → 00, 12a, ex. 10, 13, 17.

**USE** — resource metrics: Utilization, Saturation, Errors. → 00, ex. 6, 18.

**Utilization (ρ)** — the fraction of time the servers of a service center are busy: ρ = λ · S / c; waiting
grows like 1 / (1 − ρ). → 00, 01a, ex. 3.

**UvicornWorker** — a gunicorn worker (`uvicorn_worker.UvicornWorker`) with an asyncio loop; the gunicorn
timeout does not interrupt its requests (measured: 90 s → 200). → 04a, ex. 7.

**Wait budget** — the longest time a request of a given class may wait for a slot (in the course 5 s / 20 s);
after that it gets a 503 instead of waiting further. → 12a, ex. 12.

**Waiting time (W_q)** — the time a request stands in the queue for a resource (slot, connection, thread);
invisible in a profile, visible in the trace and metrics (`llm_queue_wait_seconds`). → 00, ex. 1, 6.

**Wasted work** — work nobody is waiting for any more (for example an LLM call whose client has disconnected);
cancellation and disconnect guards exist to eliminate it. → 01a, 12a, ex. 12, 18.

**`WORKER TIMEOUT`** — the gunicorn message after killing a sync worker that did not respond within
`--timeout` (30 s by default); the client gets a 500. → 04a, ex. 7.

**XLEN** — the number of entries in a Redis stream; taskiq does not delete entries, so XLEN ≠ queue length
(see: queue lag). → 14a, ex. 14.
