# Exercise 7: gunicorn — sync workers or UvicornWorker, and how many processes

> Time: ~45 min (two runs of 30 s each + a 90 s call test on each variant) + mini-incident II ~20 min

> Block II. Reading `04a-asyncio-loop-and-pools.md` (processes, threads, coroutines — who serves how many
> requests at a time).

## Goal
The production variant of the application is supposed to run behind gunicorn (port 8062). The current
configuration (`gunicorn.conf.py`) was copied from a guide for CPU-bound applications: sync workers,
`2 × CPU + 1` processes, the default `timeout 30`. You measure what that means for an application that
mostly WAITS for the LLM: throughput, memory, the queue in the socket backlog, and a call longer than 30 s.
You switch gunicorn to `UvicornWorker` with a number of processes chosen for the job.

## Theory in a nutshell
- **Sync worker** — one process = one request at a time. Throughput = number of workers / call time. With a
  3.5 s LLM call and 29 processes: ≤ 8.3 requests/s, and every process keeps a full copy of the application
  in memory. The excess waits in the socket backlog (outside the application) or gets a dropped connection.
  Pitfall: the `2 × CPU + 1` formula assumes CPU work — for I/O it has nothing to do with the core count.
- **UvicornWorker** — a gunicorn process with an asyncio loop; it runs the ASGI application
  (`app.main:app`) and serves hundreds of requests at once. You choose the number of processes based on CPU
  (JSON serialization, TLS, telemetry) and fault tolerance, and the LLM concurrency with the semaphore.
- **The semaphore is per process.** `LLM_SLOTS=32` × 2 processes = 64 calls at once. Keep the sum ≤ the
  provider's capacity and limits. Pitfall: you add processes "for performance" and unknowingly multiply the
  traffic to the provider.
- **gunicorn's `timeout`** — for sync workers: the maximum request handling time; after it the master kills
  the worker (`WORKER TIMEOUT`, the client gets a 500). For UvicornWorker: the limit on a missing process
  heartbeat (a blocked loop), not the request time. For 60–300 s calls this is the difference between "works"
  and "does not work".

## Steps
1. You stop nothing — gunicorn listens on 8062, and the application from ex. 1–6 can keep running on 8060.
   How many cores do you have? `python -c "import os; print(os.cpu_count())"` — the current configuration
   will start that many × 2 + 1 processes.
2. Start the current variant (terminal T3):
   ```bash
   gunicorn -c gunicorn.conf.py
   ```
   T2: `curl -s 127.0.0.1:8062/health` → `"server": "gunicorn-wsgi"`. The memory of all processes:
   ```bash
   ps -axo pid=,ppid=,rss=,command= | grep '[g]unicorn -c' | awk '{s+=$3} END {print NR " processes, " int(s/1024) " MB RSS"}'
   ```
3. **Hypothesis:** open-model traffic of 15/s for 30 s, each call ~3.5 s (`TOTAL_S=3` sets the generation
   time at the mock). L = λ·W = ? How many requests/s will your number of sync workers serve? What will
   happen to the rest?
   ```bash
   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/gunicorn.js -e RATE=15 -e DURATION=30s -e TOTAL_S=3 -e VARIANT=sync
   ```
   In my run (26 processes, 1658 MB RSS): 384 × 200 and **67 × `status 0`** (connection dropped — socket
   backlog full), p50 11.4 / p99 19.6 s, test 49.6 s with a 30 s inflow.
4. **A call longer than 30 s** (the mock stays silent for 90 s before the first token):
   ```bash
   curl -s -o /dev/null -w '%{http_code} after %{time_total} s\n' -X POST -H 'x-mock-ttft-ms: 90000' 127.0.0.1:8062/claims/1/summary
   ```
   In the gunicorn log (T3) look for `WORKER TIMEOUT`. In my run: `500 after 30.9 s`, 1 × `WORKER TIMEOUT` in the
   log.
5. Stop gunicorn (Ctrl+C in T3). Open **`gunicorn.conf.py`** and change it to:
   `worker_class = "uvicorn_worker.UvicornWorker"`, `wsgi_app = "app.main:app"` (the same application as
   on 8060), 2 processes, `LLM_SLOTS` per process in `raw_env` such that the sum ≤ the mock's capacity (64),
   and `APP_VARIANT=gunicorn-uvicorn` in `raw_env` (the check recognizes the variant by it). Leave a comment
   explaining why that many processes.
6. Start it again, check `/health` (`"server": "gunicorn-uvicorn"`) and the memory (step 2), repeat
   steps 3–4 with `-e VARIANT=uvicorn`. In my run (3 processes including the master, 361 MB RSS):
   **451 × 200**, 0 dropped, p50 5.6 / p99 11.6 s, slot wait p50 2.2 / p99 8.0 s; the 90 s call →
   **200 after 90.9 s**. The slot wait despite 2 × 32 ≥ L ≈ 15 × 3.5 = 52 comes from an uneven split of
   connections between processes (question 3) — in another run (the table below) p50 came out at 3.9 s;
   calculate with headroom.

   In my run (harness, the same traffic):

   | | processes / RSS | achieved | p50 | dropped | last | 90 s call |
   |---|---|---|---|---|---|---|
   | sync, 2×CPU+1 | 29 / **2111 MB** | 9.05/s | 11.3 s | **63/450** | after 49.7 s | **500 after 30.3 s** (`WORKER TIMEOUT`) |
   | UvicornWorker ×2 (32 slots/process) | 2 / **317 MB** | **13.0/s** | 3.9 s (p99 5.1 s) | 0/450 | after 34.6 s | **200 after 90.6 s** |

7. `python check.py ex07` (gunicorn must be running on 8062).

## Definition of done
- [ ] `/health` on 8062 reports `gunicorn-uvicorn`; 32 parallel requests of ~2.1 s each finish in a single
      wave (the check deliberately sends no more than one process's slots — see question 3).
- [ ] A 90 s call through gunicorn ends with a 200, not a 500.
- [ ] You can justify the number of processes and slots per process (CPU vs concurrency vs provider capacity).
- [ ] `python check.py ex07` passes.

## Review questions
1. Why, in the sync variant, did some requests end with a dropped connection rather than a 503 from the
   application?
2. You raise the sync workers' `timeout` to 600 s. What do you fix, and what is still wrong?
3. You have 2 UvicornWorker processes of 32 slots each. Will 64 simultaneous requests always split 32 per
   process? How does that affect slot wait?

Answers: `solutions/questions_answers.md`.

## ★ Bonus (optional)
Run UvicornWorker with 8 processes of 32 slots each and send 30/s traffic with `TOTAL_S=3` under the mock
profile `overload` (`curl -X POST 127.0.0.1:8061/admin/profile/overload`). What does
`sum by (status) (increase(mock_llm_requests_total[2m]))` show? Reset the mock:
`curl -X POST 127.0.0.1:8061/admin/reset`.

---

## Mini-incident II (after Block II) — "letters to customers: sometimes fast, sometimes twice as slow"

> ~20 min. Diagnose by measurement and `/diag`, without reading the code in `.run/incident-*`.

The service desk reports: at peak hours, when they send letters in bulk (several dozen at once), some
letters are generated in ~2 s and some in ~4 s — never in between. Classifications and summaries work
normally during that time.

1. Stop your own application on 8060 (gunicorn on 8062 can stay) and start the incident:
   ```bash
   ./incident.sh start mini-II
   ```
2. Reproduce the problem (the wave from ex. 5) and check the process's responsiveness during it:
   ```bash
   seq 60 | xargs -P 60 -I{} curl -s -o /dev/null -w '%{time_total}\n' -X POST \
     -H 'x-mock-ttft-ms: 2000' -H 'x-mock-total-s: 0.1' 127.0.0.1:8060/claims/{}/letter | sort -n | awk '{printf "%.2f ", $1} END {print ""}'
   curl -s -o /dev/null -w 'ping: %{time_total}\n' 127.0.0.1:8060/diag/ping
   ```
   In my run: 60 × 200; fastest 2.27 s, median 2.45 s, slowest 4.54 s — two groups (~2.3 s and ~4.4 s);
   ping during the wave 1.3 ms. `check.py ex05`: "20 of 60 requests waited for the second wave (min 2.16 s,
   max 4.36 s)".
3. Answer without looking at the code: how many requests were in the first wave? Is the event loop stuck
   (ping)? Is it the LLM semaphore (`/diag` → `queue`)? Which resource has exactly that limit?
4. Check: `python check.py ex05` — FAIL on the incident.
5. `./incident.sh stop` and back to your own application.

Answer: `solutions/questions_answers.md`, section "Mini-incidents".

---
Stuck? `solutions/hints/ex07_hint1.md` → `hint2` → `hint3`. The ready-made solution:
`solutions/ex07_gunicorn.py` → `gunicorn.conf.py`.
