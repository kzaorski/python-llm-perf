# Exercise 4: A synchronous LLM client in an `async` handler — a process that serves one request at a time

> Time: ~45 min (two open-model runs of 30 s each; the first one ends after ~1.5 min)

> Block II — asyncio, pools, processes (ex. 4–7). First read the reading
> `04a-asyncio-loop-and-pools.md` (event loop, `await`, the anyio thread pool, processes).

## Goal
The claim classification endpoint (`POST /claims/{n}/classify`) calls the LLM with a synchronous client
inside an `async def`. You look at it from the point of view of a system under load: how many requests/s
the process really serves, where the queue grows (and why NOT on the semaphore), and what happens to the
other endpoints and to `/health`. The profile and the event loop lag are only confirmation. You fix the
classification by moving it to the async path.

## Theory in a nutshell
- **Event loop** — a single thread that runs all of the process's coroutines in turns. A coroutine hands
  the loop back only at an `await`. Why: thousands of requests waiting for I/O on one thread. Pitfall: a
  blocking call (synchronous I/O, `time.sleep`) inside `async def` does not hand the loop back — the WHOLE
  process stands still.
  (→ `04a`; `00-theory.md` "The system as a network of queues")
- **Process throughput under blocking** = 1 / call time. Classification takes ~0.5 s, so a process with a
  blocked loop does ≤ 2 requests/s — regardless of slots, cores, and the provider.
- **Where is the queue then?** Not on the semaphore (requests never reach it), but in front of the loop:
  in the listening socket and in the tasks waiting for their turn in the loop. `llm_waiting` = 0,
  `Server-Timing: wait` = 0 — and the client waits tens of seconds. Pitfall: application metrics that
  measure from the entry to the handler do not see this waiting.
- **Event loop lag** — how much later than scheduled `asyncio.sleep(0.1)` wakes up. Under blocking it grows
  to the call time. The **wall-clock** profile shows where the thread stands; the **CPU** profile shows that
  nothing is computing. This confirms the cause; it is not the symptom the user experiences.

## Steps
1. State: the application after ex. 1–3 on 8060. Check it with a single request:
   `curl -s -X POST 127.0.0.1:8060/claims/7/classify` — ~0.5 s, works. A single request does not reveal
   the flaw.
2. **Hypothesis:** open-model traffic of 6 classification requests/s for 30 s. How many requests/s will the
   process serve? When will the last response arrive? What will `Server-Timing: wait` show?
3. In a second terminal measure the process's responsiveness (an endpoint with no I/O — its time = the wait
   for the loop):
   ```bash
   for i in $(seq 1 60); do curl -s -o /dev/null -w '%{time_total}\n' 127.0.0.1:8060/diag/ping; sleep 0.5; done | sort -n | tail -3
   ```
   and at the same time the open-model traffic (the scenario from ex. 7, here pointed at port 8060):
   ```bash
   docker compose run --rm -e RESULT=ex04-before k6 run -o experimental-prometheus-rw /scripts/gunicorn.js \
     -e GUNICORN_URL=http://host.docker.internal:8060 -e ENDPOINT_PATH=classify -e RATE=6 -e DURATION=30s
   ```
   In my run (exactly these commands): k6 181 requests, 179 × 200 + 2 × `status 0`, p50 **33.8 s**, p99
   **69.0 s**, the test lasted 99.8 s with a 30 s inflow; the slowest `/diag/ping` **54.5 s**; `/diag` → LLM
   queue empty (`waiting` 0) — the wait is not on the semaphore.
4. Grafana → Prometheus:
   ```
   sum by (endpoint) (rate(app_requests_total[1m]))
   max_over_time(llm_inflight{request_class="short"}[2m])
   histogram_quantile(0.99, sum by (le) (rate(app_event_loop_lag_seconds_bucket[1m])))
   ```
   Classification does not go through the semaphore, so `llm_inflight` = 0, while the event loop lag grows
   to the call time. In Tempo the `POST /claims/{n}/classify` trace has NO `llm.call` span — only the
   client's `POST` HTTP span, and between consecutive requests you can see that they run strictly one after
   another.
5. **Confirmation with the profile (optional, ~5 min).** Start the application with the profiler in wall
   mode:
   ```bash
   PYROSCOPE=1 PYROSCOPE_WALL=1 uvicorn app.main:app --port 8060
   ```
   repeat step 3 and in Grafana: Explore → Pyroscope → `claims-assistant`, label `mode=wall`.
   The hot wall-clock path leads from `classify` through the synchronous client to waiting on the socket.
   In my run: Pyroscope has a `mode=wall` label for `claims-assistant`; the wall profile has the frames
   `classify` → `Messages.create` (the synchronous SDK) → `SyncStream.read` (a socket read on the loop
   thread). With this profiler, a wave of 20 parallel classifications finished after 0.3–0.6 s (the first)
   … **10.4–11.5 s** (the last) — requests served one after another.
6. Open **`app/classification.py`** (`TODO ex. 04`). Replace the synchronous call with the application's
   async path: `await pipeline.execute(request, LLMJob(request_class="short", ...))`. As a bonus you get
   everything the LLM path has: a slot, wait measurement, telemetry, the request outcome.
7. Restart (without the profiler) and repeat step 3 with `-e RESULT=ex04-after`. In my run: 181 × 200,
   5.93/s, p50 0.53 s, p99 1.01 s, test 30.5 s; the slowest `/diag/ping` 4.8 ms.
8. `python check.py ex04` (open-model traffic of 6/s on `/classify` + a `/diag/ping` measurement in the
   background).

In my run (harness measurement: 6/s classifications + 2/s summaries in the background, 30 s):

| | achieved rate | classify p50 / p99 | `/diag/ping` | last response |
|---|---|---|---|---|
| before | 2.05/s, 22/180 dropped | 33.7 / 62.1 s | p50 2.3 s, max 10.9 s | after 87.9 s |
| after | 5.89/s, 0 errors | 0.51 / 1.00 s | p99 13 ms | after 30.5 s |

Background summaries (a different endpoint, the same process): p50 37.8 s → 1.09 s.

## Definition of done
- [ ] Under open-model traffic of 6/s the process keeps up (achieved rate ≈ inflow) and `/diag/ping`
      answers in milliseconds.
- [ ] You can explain why, before the fix, `Server-Timing: wait` = 0 while the client waited a minute.
- [ ] `python check.py ex04` passes.

## Review questions
1. Before the fix: why would increasing `LLM_SLOTS` have changed nothing?
2. Why did the summaries and `/health`, which do not use classification, slow down too?
3. How many uvicorn processes would you have to start to serve 6/s with a blocking client? Why is that a bad fix?

Answers: `solutions/questions_answers.md`.

## ★ Bonus (optional)
Instead of rewriting to `async`, wrap the synchronous call in `await asyncio.to_thread(...)`. Measure
traffic at 6/s and 60/s. What limits throughput in this variant? (Hint: ex. 5.)

---
Stuck? `solutions/hints/ex04_hint1.md` → `hint2` → `hint3`. The ready-made solution:
`solutions/ex04_classification.py` → `app/classification.py`.
