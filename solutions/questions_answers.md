# Answers to the review questions (ex. 1–18) and mini-incidents I–IV

The numbers in the answers come from the author's measurements (the same commands as in the exercises). Yours
will differ in the details — what matters is the direction and the order of magnitude.

## Ex. 01 — the first trace
1. `start_span` without activation does not set the span as the current context, so the next span
   (`llm.call`) does not become its child. Had the wait been active (`start_as_current_span`), `llm.call` would
   hang under `llm.queue_wait`, and in the trace view the wait would "contain" the call — a false picture:
   waiting time and working time would merge into one bar.
2. 40 requests / 4 slots = 10 "rounds" of ~1 s → the last one waits ~9 s and finishes after ~10 s. That is
   Little's law in the single-wave version: wait time = (position in the queue / number of slots) × service time.
3. `Server-Timing` is read by the client (browser DevTools, k6 — the `app_wait_*` trends) with no access to the
   telemetry backend; the trace is read by the application team — with context (which provider, retries, SDK
   spans). The same breakdown seen from two sides lets the client report "I waited 3 s for a slot" and lets you
   find that trace.

## Ex. 02 — open vs closed model
1. 4 VUs = at most 4 requests in the system at once; each gets a slot right away, because the previous ones are
   released before the VU sends the next. A queue cannot form — the generator itself adjusts its rate to the
   capacity (coordinated omission).
2. k6 had no free VU at the moment an iteration was scheduled to start and skipped it — the model stopped being
   open exactly when the system slowed down. The result understates the tail just like the closed model does;
   you need to give it more `preAllocatedVUs`/`maxVUs` (≥ rate × the longest response time) and repeat.
3. When the client population really is closed and waits for the response: e.g. a few claims adjusters who click
   "next claim" only after reading the summary, or a task queue worker with a fixed concurrency (ex. 14).
   Traffic from the internet / from other systems — open.

## Ex. 03 — Little's law
1. Capacity 32 / 1.06 s ≈ 30.2/s; excess 40 − 30.2 ≈ 9.8/s × 60 s ≈ **590 waiting** after a minute (with no
   queue limit). The last of them waits ≈ 590 / 30.2 ≈ **19.5 s** (and longer with every second).
2. Slots are held only by the LLM call (W in L = λ·W is the time the resource is held). The time from k6
   includes the slot wait — had you used it, under overload the "slots needed" would keep growing
   (a feedback loop).
3. The knee will shift 3× to the left (capacity ~10/s instead of ~30/s). Three times more slots means 3× more
   parallel connections, memory for in-flight responses and — above all — concurrency at the provider, whose
   limit (capacity, ITPM/OTPM) may be lower than your slots.

## Ex. 04 — a synchronous client in `async def`
1. The bottleneck is not the semaphore but the event loop: a blocking call stops the whole process, so at
   most one call is in flight at a time regardless of the number of slots.
2. All endpoints share one event loop. When it stands still (a blocking socket read in the classification
   handler), no other coroutine — summary, `/health`, `/diag/ping` — gets any time.
3. A process serves ~1 call/s, so ~6–8 processes (with headroom for the tail). Why it is a bad fix: every
   process has its own memory, its own client and limits, and the mechanism (process = 1 request) stays — with
   minute-long calls you would need hundreds of processes.

## Ex. 05 — the anyio thread pool
1. FastAPI runs `def` handlers in the anyio thread pool, whose default limiter has 40 slots
   (`anyio.to_thread.current_default_thread_limiter().total_tokens`). The 41st request waits for a free thread.
2. Every thread costs stack memory and OS context switching; with 400 threads and minute-long calls resource
   use keeps growing, and the limit only moves (at 401 parallel requests the symptom returns). On top of that,
   the threads are not subject to the application's semaphore/limiter if they call the synchronous client
   directly.
3. Ex. 4: the loop stands still — `/diag/ping` takes seconds, all endpoints suffer. Ex. 5: the loop is free —
   ping in milliseconds (in my run 1.3 ms during the wave), only the `def` endpoint suffers, and only above
   40 parallel requests.

## Ex. 06 — slot and connection pools
1. At 2/s you need ~2–3 slots; 32 is only the permitted number, not the occupied one — a semaphore costs
   nothing when it is free. With 320 slots you lose the protection: at peak you will send the provider more
   than its capacity/limit (429/529, ex. 8–9), and the queue will move from your semaphore (visible) to the
   provider (invisible).
2. With `pool=600` the wait for a connection is silent (it does not go into `llm.queue_wait`), the request
   simply takes longer. With `pool=5` pool overload produces a fast, named error (`PoolTimeout` →
   `APITimeoutError`) — you see the cause, not just the tail.
3. 4 × 32 = 128 parallel calls at capacity 64: half wait in the provider's queue or get a 529 — slots must be
   divided per process (for example 16 per process) or you need a shared limiter (Redis, ex. 8).

## Ex. 07 — gunicorn
1. The sync workers were busy, the listening socket's backlog filled up, and the kernel rejected or dropped
   connections before the application ever saw the requests (in my run 63/450 dropped). The application could
   not answer 503 because it had nothing to accept the request with.
2. You fix the worker being killed on a long call (500 + `WORKER TIMEOUT`). Throughput is still the number of
   processes / call time, and a single 600-second call blocks an entire process for 10 minutes.
3. No: the socket is shared by the kernel, and whichever process calls `accept` first takes the request — the
   distribution can be uneven. Then requests wait for a slot in one process although the other has free ones.
   Measure the wait per process (`service_instance_id`) or leave headroom in the slots.

## Ex. 08 — provider limits
1. The provider reserves OTPM according to `max_tokens` at the moment it accepts the request (it does not know
   the length of the response), so the limiter on our side has to count the same way — otherwise it will send
   too much and get a 429.
2. Each process thinks it has the whole limit — together they send ~2× too much. The `*-remaining` headers are
   the shared account state at the provider: correcting the bucket downward to `remaining` synchronizes the
   processes (with a delay of one response). The full solution: a shared limiter (e.g. in Redis).
3. A 429 concerns the account, not the request: the limit is exhausted for everyone. If the remaining requests
   keep sending, each will get a 429 (and be retried) — traffic grows and the limit takes longer to renew.

## Ex. 09 — retry storm
1. After the fix, failed requests end quickly with an error instead of "winning" on the third or ninth attempt
   against an overloaded provider. There are 7% fewer successes, but the traffic to the provider dropped from
   3.65 to 1.20 attempts/request — the provider recovers from the overload faster, and in a real system so do
   the provider's other customers.
2. ±10% around the same delay leaves clients synchronized — they come back in a wave at almost the same moment
   and overload it again. Full jitter spreads the returns evenly across the whole window.
3. In the application: it knows the retry budget, the deadline (ex. 10) and the request class, and it has the
   attempt metrics. In the SDK: correct handling of `retry-after` and idempotency without custom code. Here the
   application — because we need a budget and no retrying of timeouts; the SDK gets `max_retries=0`.

## Ex. 10 — timeouts, deadlines, cancellation
1. An SDK timeout is per operation (connect/read/write/pool), and read is the time of silence between bytes. A
   stream that sends a token (or a `ping`) every few seconds can last arbitrarily long — a 330 s "read" never
   expires. A deadline is a total limit: `asyncio.timeout()` around the whole call.
2. The 15 s read counts only from the moment the request is sent to the provider; before that the request may
   be waiting for a slot (the semaphore) and in the rate limiter. At 2/s and 15 s of slot holding, L ≈ 30 with
   32 slots — when hung calls from earlier seconds still hold slots (or other traffic is running in parallel),
   some requests wait for a slot and get their 504 later. In my repeat (just this traffic, 32 slots) there was
   no waiting — all the 504s came after 15.0 s; the extra seconds appear when L approaches the number of slots.
3. In a stream the SDK raises a raw `httpx2.ReadTimeout`, not `anthropic.APITimeoutError`. The list of retried
   / classified exceptions has to know about it — otherwise it falls into the generic "provider error" or,
   worse, gets retried by a catch-all rule (`except Exception`), multiplying multi-minute generations.

## Ex. 11 — fallback with a circuit breaker
1. 529 = the provider is overloaded, but working. A fallback moves traffic to `b` that `b` may overload too,
   and opening the breaker cuts off `a` just as it is about to recover. The right reaction to a 529 is backoff
   / a concurrency limit (ex. 8–9), not switching providers.
2. All requests would pay `a`'s timeout again if `a` is still down, and if it is just getting back up — it
   would immediately receive the full traffic and fall over again (the breaker oscillates). A single probe is
   a cheap test.
3. A `PoolTimeout` (pool < semaphore) looks like a failure of `a` (`APITimeoutError`). Without a breaker: every
   request waits for the pool timeout and quietly goes to `b`. With a breaker: after 5 such "failures" `a` is
   cut off for 30 s — all traffic goes to `b`, although `a` is healthy. Takeaway: first remove the cause (the
   pool), and have the breaker count only provider errors, not your own limits.

## Ex. 12 — backpressure and load shedding
1. After 5 minutes the client has usually given up already — the 200 goes to a client who has already left, and the slot and the
   provider's generation are wasted (run C: 30 abandoned generations). A fast 503 with `Retry-After` lets the
   client retry later or switch to another channel, and lets the system serve the ones it can still serve in time.
2. Budget ≤ the client's patience minus the service time: if the client (a browser, a proxy, another service)
   waits at most 10 s and service takes 1–2 s, a wait of more than ~5–8 s will end in abandonment anyway. The
   application knows neither the client's timeout nor whether the user is still looking — you take those
   numbers from the SLO/contract.
3. Increase capacity (more capacity at the provider, shorter responses, a second provider), shift it in time
   (a task queue with an asynchronous result), degrade (a shorter analysis). In ex. 14 — a task queue: the client
   does not hold the connection, and the wait is explicit (the age of the oldest task).

## Ex. 13 — streaming and TTFT
1. The wait for a slot and the limiter (time before the call), network/SDK overhead up to the first event, and
   the application processing and sending the first chunk.
2. Compare `app_stream_first_chunk_seconds` (the application sent) with the first chunk measured at the client
   (`scripts/stream_ttft.py` through the proxy). When the application sends after 0.5 s and the client receives
   after 3 s — the buffer is between them (proxy: turn off buffering, e.g. `X-Accel-Buffering: no`).
3. Before: the generator collects everything and does not check for a disconnect — the slot and the generation
   last to the end (3 s), then the send goes to a closed connection. After: at the next `is_disconnected()`
   check the generator finishes, the call is cancelled, the slot returns, and the provider stops generating
   (`mock_llm_cancelled_total`).

## Ex. 14 — the task queue
1. No: with 2 × 100, "fast" meant 179/200 errors of 529. 2 × 4 = 8 = the provider's capacity, so throughput
   ≈ 8 / W (in my run ~7 tasks/s) — exactly as much as the provider can give. Little: L = λ·W, with L capped
   by the provider's capacity there is no faster λ; the excess waits in the queue, where it is visible (lag 190 → 0).
2. The first worker will fetch (prefetch) up to 100 entries: `pending` in its group is almost equal to the number of tasks, the second
   one is idle. The last task finishes when the first has worked through its entire pool — the time of a single worker,
   and `lag` = 0, so autoscaling on lag will not work.
3. On the age of the oldest undelivered task (e.g. > 60 s for 5 min — according to the promise made to the customer). Queue length
   says nothing without the service rate (1000 tasks of 10 ms is nothing, 50 of 4 min is an hour); age says directly how
   long the one who has been waiting the longest has waited.

## Ex. 15 — cache stampede
1. Instead of 50 calls fighting for 32 slots (some waited for a slot) there is one call, and 49 wait only for
   its result — nobody stands in the queue for the semaphore, so p99 ≈ the time of one call.
2. The `Future` dictionary lives in the memory of one process. The second gunicorn process has its own dictionary and its own miss,
   so with N processes you get up to N calls. Across processes you need a shared point: a lock in Redis.
3. The lock will expire, the next request will acquire it and start computing a second time (two calls). That is why the lock's TTL
   > the call's deadline (the solution: 30 s = the deadline of the short calls), and after expiry the waiters compute on their own.

## Ex. 16 — batching
1. Good, because each of the 146 calls is small and short (batch ≤ 5), and a single request does not wait 2 s for the window —
   latency dropped from 2.78 to 0.54 s, and the number of calls is still several times smaller than the number of requests. It would
   be bad with a hard RPM limit (then the number of calls is the critical resource) or with a large shared
   system prompt whose cost you want to split across many claims.
2. A batch of 100 needs ~100× the input tokens at once — with 20% of the limit left it gets a 429 (or waits in the limiter) as a whole,
   all 100 customers at once. A batch of 5 fits in what remains of the limit; a 429 hits at most 5.
3. A window bounded by the SLO budget (e.g. ≤ 50–100 ms out of 1 s) and a size capped from above; under low traffic send
   immediately (an adaptive window — the bonus), under high traffic collect up to the size limit. Check both ends by measuring.

## Ex. 17 — mock vs Claude
1. A load test on the real API costs money (every request is paid for), depends on the account limits and affects
   the other users of that account; it cannot be triggered repeatably (a 429 or 529 on demand is not possible). A sequential
   measurement gives W and its distribution — the input to the capacity model; you practice behavior under load on the mock.
2. The read timeout is meant to detect a failure, not the tail: a multiple of the longest observed silence (e.g. 5–10× → 5–15 s
   for the short calls, as in ex. 10). 1.2 s would cut off an ordinary tail in a worse hour and turn it into errors.
3. W ≈ TTFT + 700 / rate: at 225 tok/s ~3.6 s, at 250 ~3.3 s, at 301 ~2.8 s. Slots = λ·W — a rate difference
   of ±20% is ±20% of slots at the same traffic.

## Ex. 18 — the final
1. See `solutions/ex18_answers.md`: `llm_inflight{request_class="short"}` stuck at 4 while the provider is
   underloaded (`mock_llm_generating` from the short requests ≈ 4) = too few slots; a correctly working queue limit
   produces 503s when the slots are running at the provider's full capacity. Show the team `llm_inflight` next to
   `mock_llm_generating`.
2. `http_req_waiting` is the time to the response headers, and `StreamingResponse` sends them right away — the
   buffer sits behind the headers. You have to measure the first chunk of the body.
3. The owner of the provider account pays (tokens generated as wasted work), and so do the other clients (provider
   slots occupied). The number: `mock_llm_cancelled_total` = 0 despite requests abandoned by k6, and
   `mock_llm_generating` > 0 for another ~2 min after the traffic ends (in my run a drain of 125 s vs 32 s after
   the fix).

---

## Mini-incidents

### Mini-I (after Block I) — "the report says OK, customers say otherwise"
- **Symptom:** k6 closed, 4 VUs: p99 1.61 s, wait 0; open traffic 4/s: p99 2.58 s, wait p99 1.46 s.
- **Evidence:** `max(llm_inflight{request_class="short"})` = 4, `llm_waiting` > 0, `llm_queue_wait_seconds` grows, and
  `mock_llm_generating` ≤ 4 (the provider is underloaded). `check.py ex06`: wait p50 21.3 s / p99 42.7 s with
  LLM 1.07 s.
- **Cause:** 4 slots — capacity ~3.8/s. The closed model adjusted itself to the capacity (coordinated omission).
- **Fix:** slots from Little's law (4/s × 1.05 s ≈ 4.2 → 8 with headroom; for 20/s → 32) + reports from the open model.

### Mini-II (after Block II) — "letters take 2 s one time, 4 s the next"
- **Symptom:** 60 simultaneous letters: two groups of times (~2.3 s and ~4.4 s), nothing in between.
- **Evidence:** `/diag/ping` during the wave 1.3 ms (the loop is free), `/diag` → `queue` empty (it is not the
  LLM semaphore), process CPU close to 0; 40 responses in the first wave.
- **Cause:** the letter endpoint is a `def` handler → the anyio thread pool (40); 20 requests wait for a free
  thread.
- **Fix:** `async def` + an async client (ex. 5); `check.py ex05` PASS.

### Mini-III (after Block III) — "the provider: you are overloading us"
- **Symptom:** the provider sees ~3× more requests than there are users, in waves; some responses are 502 (in
  my run 24/201).
- **Evidence:** `/diag` → 625 HTTP attempts for 201 requests (×3.11); at the mock 448 × 529 against 177 × 200;
  `/diag` → `clients.short.max_retries` = 2 (the SDK retries) plus application retries without jitter
  (aligned waves); `check.py ex09`: ×2.40.
- **Cause:** two layers of retries (SDK × application) with no budget and no jitter against an overloaded
  provider.
- **Fix:** a single layer (SDK `max_retries=0`), full jitter, `retry-after`, a 20% budget (ex. 9);
  `check.py ex09` PASS (in my run ×1.20).

### Mini-IV (after Block IV) — "summaries are slow while the analysis team is running"
- **Symptom:** with 40 analyses of 60 s each running in the background, a summary gets a 503 after ~5 s (in my run: 503 after 5.0 s).
- **Evidence:** `/diag` → `queue.long.inflight` = 32 (all the slots), `queue.short.inflight` = 0; `llm_inflight`
  per class — the long calls occupy the whole pool; the queue limit and the wait budget work (hence the fast 503 instead of minutes).
- **Cause:** one shared slot pool for short and long calls (head-of-line blocking).
- **Fix:** separate pools per class (32 / 16, ex. 12); `check.py ex12` PASS (short wait p99 0 ms).
