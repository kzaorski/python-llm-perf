# Exercise 14: The taskiq task queue — queue metrics and worker concurrency

> Time: ~50 min (two runs of 200 tasks, each ~0.5–1 min, plus starting the worker and the exporter)

> Block V — Task queue, cache, batching, reality (ex. 14–18). First read
> `14a-task-queues-cache-batching.md`; `00-theory.md` "Little's law", "When the arrival rate exceeds capacity".

## Goal
In ex. 12 the long analyses got a 503, because their capacity (~0.1/s) was lower than the arrival rate. The typical
architectural answer: "let's move it to a task queue". A queue does not add capacity — it moves the waiting to a place
where the client does not hold a connection. To steer it you have to see **how many are waiting** and **how long the
oldest has been waiting**, and worker concurrency must follow from the provider's capacity, not from the library's
defaults.

## Theory in a nutshell
- **Task queue** (taskiq + Redis Streams) — the application writes a job to the stream (`POST
  /claims/{n}/summary/async` → `{"task": id}`), a worker picks it up and runs it, the result sits in Redis
  (`GET /jobs/{id}` → `pending_or_running` | `done` | `error`). Intuition: the semaphore from ex. 06, only durable and
  shared across processes. (→ `14a`)
- **Queue length ≠ `XLEN`** — taskiq does not delete processed entries from the stream, so `XLEN` grows with every
  job. The queue is described by the consumer group: `lag` (not yet delivered), `pending` (delivered, unacknowledged)
  and the age of the oldest undelivered entry (entry ID = timestamp in ms).
- **Worker concurrency** = `--workers` × `--max-async-tasks`. From Little's law: L = λ·W — with a provider capacity of 8
  concurrent generations and ~1.6 s per task, throughput ≈ 5 tasks/s; more parallelism only gives 529 (overloaded).
- **Prefetch** (`xread_count`) — how many entries a process fetches "just in case". The trap: fetched = delivered, so
  they vanish from `lag` — the queue looks empty even though nothing has been done, and one process can hoard everything.

## Steps
1. State after ex. 13, application on 8060. In two new terminals (T2, T3) start a worker with the **default** taskiq
   settings and the queue metrics exporter:
   ```bash
   taskiq worker app.tasks:broker --workers 2 --max-async-tasks 100     # T2
   python -m app.queue_metrics                                          # T3 → http://127.0.0.1:8063/metrics
   curl -s 127.0.0.1:8063/metrics | grep -E '^queue_'
   ```
   For now the exporter shows only `queue_xlen`.
2. **Hypothesis:** you will enqueue 200 background summaries with the `overload` mock profile (the provider's capacity is
   8 generations + a queue of 8). The worker has 2 × 100 = 200 places. How many tasks will end with an error? What will
   `XLEN` show when they finish?
3. Enqueue 200 tasks and observe:
   ```bash
   curl -s -X POST 127.0.0.1:8061/admin/profile/overload
   for i in $(seq 200); do curl -s -o /dev/null -X POST 127.0.0.1:8060/claims/$i/summary/async; done
   curl -s 127.0.0.1:8063/metrics | grep -E '^queue_'
   ID=$(curl -s -X POST 127.0.0.1:8060/claims/7/summary/async | python -c 'import json,sys; print(json.load(sys.stdin)["task"])')
   curl -s 127.0.0.1:8060/jobs/$ID
   ```
   In Prometheus (after ~10 s; the worker's counter counts from the process start, so look at the value, not at
   `increase()` — the series is born right away with its full value and `increase` shows 0; `service_instance_id`
   separates successive worker starts — the series of the previous process stays visible for a few more minutes):
   ```
   sum by (outcome, service_instance_id) (tasks_completed_total)
   queue_xlen
   ```
   In my run: all 201 tasks were settled in ~2 s — **170 × `OverloadedError`** (529) and 31 × `ok`; the last task:
   `"state": "error"`. `queue_xlen` 380 → 418 → 581 in successive readings and it never goes down (it also counts
   the entries from earlier runs).
4. **Queue metrics.** In **`app/queue_metrics.py`** (`TODO ex. 14`) add the gauges `queue_lag`,
   `queue_pending`, `queue_oldest_age_seconds` (and optionally `queue_oldest_pending_age_seconds`):
   `XINFO GROUPS` → `lag`, `pending`, `last-delivered-id`; the first entry after `last-delivered-id` (`XRANGE`
   with an exclusive start `(`) → its age. Restart the exporter (T3), `curl … | grep ^queue_`.
5. **Hypothesis before the repeat:** with the new metrics, with the same 2 × 100 worker, what will `queue_lag` be
   during the run? Why?
6. Repeat step 3 (`POST /admin/reset` on the mock before and after) and observe:
   ```
   max_over_time(queue_lag[5m])
   max_over_time(queue_pending[5m])
   max_over_time(queue_oldest_age_seconds[5m])
   ```
   In my run (2 × 100, prefetch 100): **179/200 tasks with an error** in 6 s (220 responses of 529 at the mock), and
   `queue_lag` max **0** — the prefetch took everything, the queue was "empty", even though almost nothing had succeeded.
7. **Worker concurrency (F15).** In **`app/tasks.py`** set the prefetch equal to the per-process concurrency
   (`TASKS_MAX_ASYNC`, default 4) and start the worker so that the total equals the provider capacity set aside for tasks:
   ```bash
   taskiq worker app.tasks:broker --workers 2 --max-async-tasks 4      # T2, 2 × 4 = 8
   ```
8. Restart the worker, `POST /admin/reset`, repeat step 3 and the queries from step 6. In my run (2 × 4): **201/201
   done**, the mock 201 × 200 and **0 × 529**, the last task after 28 s; `queue_lag` max 176 → 0 (samples every 2 s),
   `queue_oldest_age_seconds` max 19.3 s, `pending` ≈ 8–9. For comparison, the run from step 6 (2 × 100, new
   exporter): 171 × `OverloadedError` / 30 × `ok` in 2 s, the mock 212 × 529, `queue_lag` max **0**, `pending` 26.

   In my run: **200/200 tasks OK** in 28.7 s, 0 × 529, `queue_lag` max 190 → 0 (the queue visible and draining at ~7/s).
9. `python check.py ex14` (the exporter with `queue_lag` and `queue_oldest_age_seconds` on 8063; 60 tasks with
   `overload` — all done, 0 errors). Leave the worker and exporter running until the end of the block or stop
   them (Ctrl+C) — the following exercises do not need them.

## Definition of done
- [ ] `queue_lag`, `queue_pending`, `queue_oldest_age_seconds` are on :8063; after the end of the inflow lag returns to 0.
- [ ] You can explain why `XLEN` is not the queue length and why lag = 0 with a large prefetch.
- [ ] Worker concurrency (`--workers` × `--max-async-tasks`) follows from the provider's capacity; 0 errors of 529.
- [ ] `python check.py ex14` passes.

## Review questions
1. With 2 × 4 all 200 tasks succeeded, but it took 28.7 s instead of 6 s. Is that a worse result? What does Little's law say about it?
2. You have two workers on different machines and a prefetch of 100. The first one started 2 s earlier. What will you see in
   `pending` and in the finish time of the last task?
3. What values of `queue_oldest_age_seconds` would you set an alert on, and why age rather than queue length?

Answers: `solutions/questions_answers.md`.

## ★ Bonus (optional)
Move the long analyses from ex. 12 to the task queue (enqueue + `GET /jobs/{id}`). Run `k6/mixed.js` and compare
with run B from ex. 12: instead of 42 rejections with a 503 you have a queue — what age of the oldest task does it reach,
and when does that stop being acceptable?

---
Stuck? `solutions/hints/ex14_hint1.md` → `hint2` → `hint3`. The ready solution:
`solutions/ex14_queue_metrics.py` → `app/queue_metrics.py` and `solutions/ex14_tasks.py` → `app/tasks.py`.
