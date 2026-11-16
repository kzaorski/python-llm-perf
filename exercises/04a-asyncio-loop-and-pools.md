# 04a. Reading: asyncio, the event loop and pools — from the system's point of view under load

A reading, not an exercise — no tasks and no definition of done. Goal: understand
the application's concurrency model (one event loop, coroutines, a thread pool, a
semaphore, a connection pool, processes) as a **set of service centers with
limits** — before you start clogging and unclogging them in Block II. The asyncio
basics are laid out from scratch here, but the emphasis is on what happens to
queues and throughput under traffic, not on the microscopic behavior of a single
process. Every concept follows the same pattern:

> **Definition** → **Intuition/analogy** → **Why it matters** → **Common mistake**

Come back here whenever things stop adding up. Short definitions are in `glossary.md`.

---

## The event loop

**Definition.** The asyncio **event loop** is a single thread that keeps doing the
following: (1) asks the operating system which sockets have data or are ready for
writing (the selector: `kqueue` on macOS, `epoll` on Linux), (2) wakes the
coroutines that were waiting for those events, (3) runs each of them **up to the
nearest `await`**, (4) goes back to step 1. Every request handled by a uvicorn
process shares this one loop and this one thread.

**Intuition.** A waiter serving 50 tables: takes an order, carries it to the
kitchen and **does not stand at the pass** — he walks on to the next table and
comes back when the kitchen rings the bell. One waiter is enough as long as no
task requires him to stand still. If one table makes him wait beside it for
2 minutes, the other 49 wait with him.

**Why it matters.** An LLM application spends almost all its time waiting for the
network — and waiting costs nothing in asyncio: a thousand coroutines waiting for
the provider are a thousand small objects in memory and one thread. That is why a
single uvicorn process handles dozens of parallel LLM calls. But the loop is a
**single-server center** (c = 1) for all code that runs between `await`s: if that
code takes long, the queue of ready coroutines grows and every one of them —
`/health` included — waits.

**Common mistake.** "Async means parallel." It does not: coroutines run **in
turns** on one thread. Only the waiting happens in parallel (in the sense of "at
the same time") — for the network, the disk, a timer. Python computation is
limited by the GIL anyway, and inside the event loop — by its single thread.

---

## Coroutine, `await`, task

**Definition.**
- **Coroutine** — an `async def` function; calling it returns a coroutine object
  that runs only when someone `await`s it or wraps it in a task.
- **`await x`** — "suspend me until `x` is ready"; hands control back to the loop.
  It is the only place where another coroutine can get time.
- **Task** (`asyncio.Task`) — a coroutine scheduled on the loop that runs
  independently (for example, each HTTP request in uvicorn is a separate task).
  A task can be **cancelled** (`task.cancel()`): at the point where it is waiting,
  it receives a `CancelledError` exception.

**Intuition.** A bookmark in a book. `await` is putting in the bookmark and
setting the book down — the waiter (the loop) can read another one in the
meantime. Cancellation is taking the bookmark out and closing the book: at the
next opportunity the reader learns that he is supposed to stop.

**Why it matters.** Two things matter under load:
1. **A suspended coroutine uses no thread and no CPU** — which is why it is
   invisible in a profile but perfectly visible in a trace (the span lasts) and in
   metrics (`llm_inflight`, `llm_waiting`).
2. **Cancellation is the only way to release the resources held by a waiting
   task** — a semaphore slot, a connection, a generation at the provider.
   `asyncio.timeout(60)` (the total deadline) and the client-disconnect guard both
   work through cancellation (readings 08a and 12a, ex. 10).

**Common mistake.** Calling a coroutine without `await` ("but I called the
function") — nothing runs, and Python prints the warning *coroutine was never
awaited*. Another: wrapping an `await` in `except Exception` in the belief that it
catches cancellation — `CancelledError` inherits from `BaseException`, and
swallowing it breaks the deadline mechanism.

---

## Blocking the loop

**Definition.** **Blocking the loop** means running code inside a coroutine that
takes a long time **without an `await`**: a synchronous network call
(`anthropic.Anthropic`, `requests`, `time.sleep`), heavy computation, a
synchronous read of a large file. For that time the loop serves nobody. The
measure is **event loop lag** — the delay with which the loop runs a callback
scheduled "in a moment" (in the application: `app_event_loop_lag_seconds`,
`loop_lag_max_10s_ms` in `/diag`).

**Intuition.** A waiter who personally waits at the kitchen until the dish is
ready. The restaurant then serves one table at a time — regardless of how many
tables and cooks it has.

**Why it matters.** The system-level consequence is much more serious than "one
slow request". In ex. 4, a synchronous LLM client in an `async def` handler:
- a burst of 20 classifications of 0.5 s each takes **10.55 s** = 20 × 0.5 s — in
  series; the loop lag reaches 6.6 s;
- open-model traffic of 6/s classifications + 2/s summaries: the process finishes
  **2.05/s**, classification p99 is 62 s, 22 of 180 requests are dropped,
  `/diag/ping` (which does nothing) waits up to 10.9 s, and the last response
  arrives 88 s after the start of the 30-second test;
- after the fix (an async call): 5.89/s, p99 1.0 s, ping p99 13 ms.

From the queueing-theory point of view the loop became a single server whose
service time equals the LLM call time — capacity drops to 1 / 0.5 s = 2/s. The
queue grows in places the semaphore cannot see (semaphore wait = 0): in the
socket and in the loop. All endpoints suffer, the health check included — the
container orchestrator may start restarting a "dead" process.

**Common mistake.** Looking for the blocking only in the CPU profile. A
synchronous client waits on a socket, so in the CPU profile it takes a fraction of
a percent; in the wall-clock profile it is visible (`SyncStream.read`). The
fastest proof, though, is the system-level symptom: achieved rate ≈ 1 / call time
and event loop lag measured in seconds.

---

## `def` vs `async def` in FastAPI and the anyio thread pool

**Definition.** FastAPI (through Starlette and the anyio library) runs a handler
defined as a plain `def` **in a thread pool**, so that it does not block the
loop. `run_in_threadpool` / `anyio.to_thread.run_sync` work the same way. The
pool has a default **limiter of 40 concurrent threads** (`total_tokens = 40`,
verified in anyio 4.15). A call over the limit waits for a free token — with no
CPU use, no span, no metric.

**Intuition.** There are 40 doors into the kitchen. The waiters (threads) who
entered with a synchronous order stand inside until the dish is ready. The
forty-first waits outside the door — although nobody in the kitchen is doing
anything, everybody is waiting for the oven.

**Why it matters.** The thread pool is a center with c = 40 and a service time
equal to the **whole** synchronous call (including the wait for the network).
Ex. 5: 60 concurrent letters of ~2.1 s each → ⌈60 / 40⌉ = 2 waves: 40 finish
after 2.2 s, 20 after 4.35 s (p99 4.36 s); after rewriting to `async def` with an
async client: one wave, p99 2.28 s. The pool's capacity for such calls:
40 / 2.1 s ≈ 19/s — for minute-long calls 40 / 150 s ≈ 0.27/s. The characteristic
symptom: response time grows in **steps** every 40 requests.

**Common mistake.** "Let's raise the limiter to 1000." Every thread costs memory
(its stack) and contends for the GIL; a pool of 1000 threads waiting for the
network does what a single loop would do for free. A second mistake: the limit of
40 is **shared** by the whole process — one slow synchronous module eats the
tokens of the other `def` handlers and of every `run_in_threadpool` call.

---

## Semaphore: an explicit concurrency limit

**Definition.** `asyncio.Semaphore(n)` lets at most *n* coroutines through at a
time; the others wait (suspended) in its internal queue until someone releases a
slot. In the course application the LLM semaphore (the `app/llm/limiter.py`
module) is the **main, explicit concurrency limit toward the provider**: it has
separate slots per class (short / long), measures the wait time (span
`llm.queue_wait`, histogram `llm_queue_wait_seconds`) and exposes occupancy
(`llm_inflight`), the number of waiting requests (`llm_waiting`) and the age of
the oldest waiting request.

**Intuition.** A parking-lot gate with a free-spaces counter. The queue in front
of the gate is visible — which is why you prefer it to invisible queues inside.

**Why it matters.** The semaphore turns hidden queues (in the connection pool, at
the provider — 429/529) into **one queue that you can see and control**. You size
it with Little's law: for 20 summaries/s of 1.06 s each you need 21 slots on
average; 4 slots give a capacity of 3.77/s and, at 20/s, a p50 wait of 32 s
(ex. 6), while 32 slots give a p99 wait of 0. You then add a queue length limit
and a wait budget on top of the semaphore (ex. 12).

**Common mistake.** A semaphore without a wait measurement. If the wait span is
the **parent** of the call (not its sibling), the call time is included in the
wait — and the chart looks as if everything were queue. Another mistake: with
several processes each has its **own** semaphore — the global limit is processes
× slots (ex. 7: `LLM_SLOTS` is per process).

---

## Connection pool in httpx / httpx2

**Definition.** An HTTP client keeps a **connection pool** of TCP connections
(with keep-alive) to each host. `httpx.Limits` / `httpx2.Limits` set
`max_connections` (how many at once) and `max_keepalive_connections` (how many
idle ones to keep). The defaults in httpx 0.28 and httpx2 2.16 are **100 / 20**
with a 5 s timeout. The `anthropic` 2.3 SDK (built on httpx2) creates its own
client with a limit of **1000 connections** and timeouts of **connect 5 s,
read/write/pool 600 s**. A request that did not get a connection waits in the pool
until the `pool` timeout, then receives `PoolTimeout` — visible in the SDK as
`anthropic.APITimeoutError`.

**Intuition.** A company with a fleet of 8 cars. There may be 64 drivers
(coroutines let through by the semaphore), but only 8 are driving at a time — the
rest sit in the office with the keys in hand and count it as "driving time".

**Why it matters.** The pool is the second center with a limit after the
semaphore. If it is **smaller** than the semaphore, it becomes a bottleneck you
cannot see in the wait span. The ex. 6 variant: semaphore 64, pool 8 — at most
**8** generations at once at the provider, "LLM call" p50 8.2 s for a 1-second
generation, overall p99 24.7 s. With the default `pool = 600 s` the pool wait is
silent; with `pool = 5 s` (after ex. 10) it comes out: 86 / 300 requests end in a
504 (`APITimeoutError` caused by `PoolTimeout`) — and with fallback enabled, 77
requests quietly move to the fallback provider. The rule: **one explicit limit**
(the semaphore) and a pool ≥ the semaphore, or the pool as the limit, but then
with a measured wait time.

**Common mistake.** A new HTTP client (or a new `AsyncAnthropic`) for every
request "to keep things clean" — every call pays for connection setup and TLS,
and the pool limits stop meaning anything. There is **one client per process** and
it lives as long as the application. A second mistake: `except APIConnectionError`
with "dropped connections" in mind — `APITimeoutError` is its subclass, so that
branch also catches `PoolTimeout` and read timeouts.

---

## Processes: gunicorn sync vs UvicornWorker

**Definition.** One Python process is one loop (and one GIL). To use several cores
or to isolate failures, you run several processes under a manager — in the course
it is **gunicorn**:
- **`-k sync`** — each process handles **one request at a time** (a WSGI
  application). The popular heuristic for the number of processes, **2 × CPU + 1**
  (29 on the author's machine), comes from the world of CPU-bound workloads; for
  I/O, capacity is processes / call time. The default `--timeout 30`: a process
  that has not answered the supervisor within 30 s is killed (`WORKER TIMEOUT`).
- **`-k uvicorn_worker.UvicornWorker`** (the `uvicorn-worker` package) — each
  process is a full asyncio loop with many requests at once; the process's
  concurrency is set by the semaphore (32 slots per process in the course). The
  gunicorn timeout here concerns the process's heartbeat, not the request time.

Requests that no process has accepted wait in the **socket backlog** (a queue in
the kernel); when it overflows, the client gets a dropped connection.

**Intuition.** `sync` is 29 checkout lanes, each with a cashier who, after
scanning the goods, stands and waits for the customer to find a wallet.
UvicornWorker is two self-service checkouts with an attendant watching 32
customers at once.

**Why it matters.** Ex. 7, 15 requests/s of ~3.5 s each (L ≈ 52):
- `-k sync`, 29 processes: capacity 29 / 3.5 ≈ 8.3/s (measured 9.05/s); p50
  11.3 s, **63 / 450** connections dropped (backlog), **2111 MB** of memory; a
  single 90 s request → **500 after 30.3 s** (worker killed);
- UvicornWorker × 2 (2 × 32 slots ≈ 18/s capacity): achieved 13.0/s, 450 / 450 OK,
  p50 3.9 s, **317 MB**; a 90 s request → **200 after 90.6 s**.

For 60–300 s calls `-k sync` is indefensible: a process is busy for minutes, the
30 s timeout kills it mid-call, and raising `--timeout` only hides the fact that
capacity is a few requests per minute.

**Common mistake.** Multiplying processes without recomputing the global limit.
Two processes of 32 slots each are 64 parallel calls at the provider — if its
capacity or token limit is lower, the extra process only adds 429/529s. The number
of processes follows from CPU and fault tolerance; the concurrency toward the
provider follows from its limits.

---

## The GIL in one paragraph

**Definition.** The **GIL** (*global interpreter lock*) in CPython allows only one
thread at a time to execute Python code. A thread waiting for I/O (a socket,
`sleep`) releases the GIL.

**Intuition.** One microphone in the room — only the person holding it speaks;
whoever is waiting for a reply from the network puts the microphone down.

**Why it matters.** For an I/O-bound application the GIL hardly matters: the pool
threads and the loop mostly wait anyway. It matters when CPU work appears next to
the waiting (parsing large responses, tokenization, serialization) — then the
threads and the loop fight for the one "microphone" and event loop lag grows.

**Common mistake.** Adding threads to a problem that is a semaphore queue or a
provider limit. Threads do not increase the capacity of the center behind them.

---

## How it all fits together (map)

```
 gunicorn (processes) ── socket backlog (kernel) ──┐                       [ex. 7]
   -k sync: 1 request/process, timeout 30 s        │
   UvicornWorker: loop + 32 slots/process          ▼
                         ┌── event loop (1 thread, c = 1 for code between awaits) ── event loop lag [ex. 4]
                         │      ├─ `def` / run_in_threadpool ──► anyio: 40 threads (waves every 40) [ex. 5]
                         │      ▼
                         │   LLM semaphore (slots per class, wait measured)           [ex. 1, 6, 12]
                         │      ▼
                         │   httpx2 pool (SDK: 1000; pool timeout 600 s → wait hidden) [ex. 6]
                         │      ▼
                         └── await on the provider: coroutine suspended — trace YES, profile NO
 global concurrency toward the provider = processes × slots  ≤  its capacity and limits (reading 08a)
```

Now move on to ex. 4.
