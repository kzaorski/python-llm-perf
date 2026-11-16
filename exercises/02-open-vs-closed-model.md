# Exercise 2: k6 — open vs closed model (coordinated omission)

> Time: ~40 min (two k6 runs of 60 s each + analysis)

> Block I. Theory: `00-theory.md` "Open vs closed model and coordinated omission", "Percentiles and the tail";
> block reading `01a-queueing-theory-in-practice.md`.

## Goal
You send the same traffic with two load generators: a closed one (a fixed number of virtual users,
each waiting for its response) and an open one (requests at a constant rate, regardless of the
responses). You will see that the closed model's report looks "pretty" because the generator itself
slows down when the system slows down — and it does not see the queue. You complete the open scenario
in `k6/open_model.js`.

## Theory in a nutshell
- **Closed model** (`constant-vus`) — N users in a loop "send → wait → (pause) → send". The rate is NOT
  a parameter: it equals N / (response time + pause). When the system slows down, the generator sends
  less. Why it matters: it models a fixed pool of clients (e.g. N batch workers). Pitfall: "4 VUs" is
  not "4 requests/s".
- **Open model** (`constant-arrival-rate`, `ramping-arrival-rate`) — requests arrive at a given rate λ,
  like customers from the internet who know nothing about your queue. Why it matters: only this model
  shows the queue and the real tail. Pitfall: k6 needs a sufficient VU pool — when it runs out, it
  "closes" the model by itself and drops iterations (`dropped_iterations` > 0).
- **Coordinated omission** — a generator that waits for the response "conspires" with the system:
  during a stall it sends no requests, so it does not measure their (nonexistent) waiting. The report
  understates the tail exactly where it hurts most. (→ `00-theory.md`; `glossary.md`)
- **Achieved rate** — always report next to the percentiles how many requests/s were actually sent.
  Comparing the p99 of two tests makes sense only at the same intensity.

## Steps
1. State after ex. 1: the application on 8060 (`uvicorn app.main:app --port 8060`), 4 LLM slots. A
   summary takes ~1 s, so the capacity ≈ 4 / 1.05 s ≈ 3.8 requests/s.
2. **Closed model**, 4 VUs with no pause, 60 s (terminal T2):
   ```bash
   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/closed_model.js -e VUS=4 -e PAUSE_S=0 -e DURATION=60s
   ```
   The summary also goes to `results/ex02-closed.json`. Note down: `http_reqs` (rate/s),
   `http_req_duration` p99, `app_wait_short` p99.
3. **Before you run the open model:** the same system, nominally the same intensity (4 requests/s).
   Will the p99 be similar? What will `app_wait_short` show?
4. Open **`k6/open_model.js`** and complete `options.scenarios` (TODO ex. 02): an open-model executor
   with a constant rate `RATE` requests/s for `DURATION`, with a VU pool chosen so that
   `dropped_iterations` is 0.
5. **Open model**, 4/s, 60 s:
   ```bash
   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/open_model.js -e RATE=4 -e DURATION=60s
   ```
   In my run (state after ex. 1):

   | Model | Achieved rate | p50 / p99 | wait p99 | dropped |
   |---|---|---|---|---|
   | closed, 4 VUs with no pause | 3.75/s | 1.04 / **1.57 s** | 0 | 0 |
   | open, 4/s | 3.52/s (arrival rate 4/s > capacity ~3.8/s) | 2.99 / **4.41 s** | 3.28 s | 0 |

   The closed model does not see the queue (wait 0 — each VU waits for its own response, so there are
   never more than 4 requests at once). The open model, at the same nominal intensity, shows the queue
   on the semaphore.
6. The pitfall "VU = requests/s": repeat the closed model with a 1 s pause:
   ```bash
   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/closed_model.js -e VUS=4 -e PAUSE_S=1 -e DURATION=40s
   ```
   In my run the rate dropped to **1.92/s** — the model slowed itself down to half, and the report still
   looks "healthy" (p99 1.63 s). This run overwrote `results/ex02-closed.json` — for the check either of
   the two closed runs is enough.
7. Prometheus (k6 sends metrics through remote write, tag `model`):
   ```
   max by (model) (k6_http_req_duration_p99)
   max by (model) (k6_app_wait_short_p99)
   sum by (model) (k6_dropped_iterations_total)
   ```
8. `python check.py ex02`

## Definition of done
- [ ] `k6/open_model.js` has a `constant-arrival-rate` scenario; the 4/s run has `dropped_iterations` = 0.
- [ ] You can point out in the results why the closed model's p99 is lower even though the system is the same.
- [ ] In every comparison you report the achieved rate, not the number of VUs.
- [ ] `python check.py ex02` passes (open p99 > 1.3 × closed, 0 dropped iterations).

## Review questions
1. Why, in the closed model with 4 VUs, is the semaphore wait 0 when the application has 4 slots?
2. What does `dropped_iterations` > 0 mean in the open model, and why does it invalidate the result?
3. When IS the closed model the right one? Give an example from this application.

Answers: `solutions/questions_answers.md`.

## ★ Bonus (optional)
In `k6/open_model.js` deliberately set too few VUs (`preAllocatedVUs: 2, maxVUs: 4`) and run 4/s. How
many iterations did k6 drop and how did the p99 change? It is the same mistake as the closed model,
only hidden in the configuration.

---
Stuck? `solutions/hints/ex02_hint1.md` → `hint2` → `hint3`. The ready-made solution:
`solutions/ex02_open_model.js` → `k6/open_model.js`.
