# Exercise 3: Little's law and the knee of the curve — how many slots do you need?

> Time: ~45 min (two ramps of ~2.5 min + calculations) + mini-incident I ~20 min

> Block I. Theory: `00-theory.md` "Little's law", "Utilization and waiting time: the knee of the curve",
> "When the arrival rate exceeds capacity"; block reading `01a-queueing-theory-in-practice.md`.

## Goal
You determine the application's capacity in two ways — by calculation (Little's law) and by measurement
(a rate ramp in the open model) — and check that they agree. You find the "knee": the rate from which
waiting grows faster than throughput. You do not change any code; you only change the number of slots
with the `LLM_SLOTS` variable.

## Theory in a nutshell
- **Little's law: L = λ · W** — the average number of requests in the system (L) = the arrival rate (λ)
  × the average time in the system (W). It holds for any stable queue, with no assumptions about
  distributions. Why it matters: from λ and the LLM call time you work out how many calls will be in
  flight — that is, how many slots you need. Pitfall: when you count slots, W is the SERVICE time
  (waiting does not occupy a slot); and it is an average — for the tail you need headroom.
- **Capacity (maximum throughput)** = slots / service time. With 4 slots and ~1.05 s:
  ≈ 3.8 requests/s. Above that the queue grows without bound (arrivals > departures).
- **Utilization (ρ) and the knee** — ρ = λ / capacity. The waiting time grows nonlinearly with ρ (for a
  simple model ~ ρ/(1−ρ)): at 50% almost zero, at 90% a few service times, at 100% unbounded. The knee
  is the place on the rate → waiting curve where that growth starts. Why it matters: you plan work
  BELOW the knee. Pitfall: an average utilization of 70% over a 5-minute window hides minutes above 100%.
- **Saturation** — a resource (here: the slots) 100% busy: `llm_inflight` stuck at the number of slots.
  That is the "S" in USE. (→ `00-theory.md` "RED and USE for this application")

## Steps
1. **Calculation first.** A summary on the mock takes ~1.05 s (the p50 of LLM service time from ex. 1–2).
   How many requests/s can 4 slots handle? How many slots do you need for 20/s? For 30/s? Write the numbers down.
2. **Hypothesis:** a ramp from 1 to 6 requests/s in steps of 1/s, 20 s per step. At which step will
   waiting start to grow? What will `llm_inflight{request_class="short"}` be then?
3. The ramp on 4 slots (the application after ex. 2, started as usual):
   ```bash
   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/ramp.js -e FROM=1 -e TO=6 -e STEP_RPS=1 -e STEP_S=20
   ```
   It takes ~2.5 min. While it runs, watch in Grafana (Explore → Prometheus, range "Last 5 minutes",
   mode "Range"):
   ```
   sum(rate(app_requests_total{endpoint="summary"}[20s]))
   max(llm_inflight{request_class="short"})
   histogram_quantile(0.9, sum by (le) (rate(llm_queue_wait_seconds_bucket{request_class="short"}[20s])))
   ```
   In my run (456 requests; values every 20 s from Prometheus, `query_range`):

   | t [s] | 20 | 40 | 60 | 80 | 100 | 120 | 140 | 160 |
   |---|---|---|---|---|---|---|---|---|
   | achieved rate [/s] | 0.9 | 1.9 | 2.2 | 3.4 | 3.6 | 3.6 | 4.0 | 2.9* |
   | `llm_inflight` max | 2 | 3 | **4** | 4 | 4 | 4 | 4 | 4 |
   | wait p90 [s] | 0 | 0 | 0 | 0.85 | 2.7 | 7.3 | 14.4 | 19.7 |

   \* after the end of the inflow (draining). The rate stalls at ~3.6–4/s, the slots are stuck at 4, and
   waiting grows with every step — k6 at the end: wait p99 19.6 s with LLM service ~1 s.
4. **Changing the capacity without changing code.** Stop the application and start it with the number of
   slots you calculated for ~30/s (I took 32):
   ```bash
   LLM_SLOTS=32 uvicorn app.main:app --port 8060
   ```
5. **Hypothesis:** where will the knee fall with 32 slots? (32 / 1.06 s ≈ ?)
6. The second ramp, from 4 to 44 requests/s in steps of 8, 20 s each:
   ```bash
   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/ramp.js -e FROM=4 -e TO=44 -e STEP_RPS=8 -e STEP_S=20
   ```
   In my run (~22 s windows from Prometheus):

   | Step [requests/s] | 4 | 12 | 20 | 28 | 36 | 44 |
   |---|---|---|---|---|---|---|
   | achieved rate [/s] | 8* | 15 | 20.5 | 29.2 | 29.8 | 30.2 |
   | `llm_inflight` max | 13 | 24 | 31 | **32** | 32 | 32 |
   | wait p90 [s] | 0 | 0 | 0 | 1.6 | 6.1 | 9.7 |

   \* the rate windows overlap the transitions between steps — read the trend, not a single cell.
   The knee ≈ 28–30/s = 32 slots / 1.06 s (Little). Above it the rate stands still, and waiting grows
   with every step — that is the excess waiting in the queue. In total: 2,997 requests, wait p99 9.6 s.
7. **A note about the generator.** At 36–44/s k6 reported in my run `dropped_iterations` 130 and 45
   `dial: i/o timeout` errors (status 0). That is k6 in a Docker Desktop container, which cannot keep up
   with new connections to `host.docker.internal`, not the application's responses (the application did
   not register those requests — check `app_requests_total`). Report them separately. Above the knee
   you do not plan work anyway.
8. Go back to the normal way of starting the application (without `LLM_SLOTS`) — you will change the
   default number of slots in the code in ex. 6.
9. `python check.py ex03` (checks that there is a ramp record `results/ex03-ramp.json` with ≥ 200 requests).

## Definition of done
- [ ] The number of slots calculated from Little's law agrees with the knee measured by the ramp (±15%).
- [ ] You can point on the chart to: saturation (`llm_inflight` = slots), the start of the queue, the flat rate.
- [ ] You understand why increasing the slots moved the knee but did not remove it.
- [ ] `python check.py ex03` passes.

## Review questions
1. The application has 32 slots, a call takes 1.06 s. An arrival rate of 40/s for one minute. How many
   requests are waiting after a minute, and how long does the last of them wait?
2. Why do you use the LLM service time, not the response time from k6, to count slots?
3. The LLM call gets longer, from 1 s to 3 s (longer responses). What happens to the knee? And to the
   cost of memory/connections if you increase the slots 3×?

Answers: `solutions/questions_answers.md`.

## ★ Bonus (optional)
Draw a "wait p90 vs utilization" panel in Grafana (`max(llm_inflight{request_class="short"}) / 32` on the
X axis — in Explore two queries on one chart are enough). Compare the shape with the ρ/(1−ρ) curve.

---

## Mini-incident I (after Block I) — "the test report says OK, customers say otherwise"

> ~20 min. You diagnose ONLY through k6, Grafana and `/diag` — do not read the code in `.run/incident-*`.

The test team sent a report: "4 VUs, 30 s, p99 1.6 s, 0 errors — performance OK". After the deployment,
at ~4 claims/s, customers complain about responses taking 3 s and longer.

1. Stop your own application (port 8060 must be free) and start the incident:
   ```bash
   ./incident.sh start mini-I
   ```
2. Reproduce the team's report and what the customers see:
   ```bash
   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/closed_model.js -e VUS=4 -e PAUSE_S=0 -e DURATION=30s
   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/open_model.js -e RATE=4 -e DURATION=30s
   ```
   In my run: closed 3.69/s, p99 **1.61 s**, wait 0; open 121 requests in 30 s (k6 computes the rate with
   draining: 2.63/s), p99 **2.58 s**, wait p99 1.46 s; `check.py ex06`: slot wait p50 21.3 s / p99 42.7 s
   with LLM 1.07 s.
3. Answer based on the metrics (without the code): where do the requests lose time? Which resource is
   saturated and how can you tell (`llm_inflight`, `llm_queue_wait_seconds`, `mock_llm_generating`)? Why
   did the team's report not show it? How many slots do you need for 4/s with headroom, and how many for
   the target 20/s?
4. Check: `python check.py ex06` (the ex. 6 probe — open traffic at 20/s) — on the incident it FAILs with numbers.
5. `./incident.sh stop`, then start your own application again.

Answer (symptom → evidence → cause → fix): `solutions/questions_answers.md`, section "Mini-incidents".

---
Stuck? `solutions/hints/ex03_hint1.md` → `hint2` → `hint3`. This exercise has no code to copy — the
hints walk you through the calculation.
