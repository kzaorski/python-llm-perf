# Exercise 18: Final — the incident "everything slowed down on Monday morning"

> Time: ~90 min: incident traffic ~4 min + drain up to ~2.5 min (you will run it 2–3 times), diagnosis, report,
> fix and a comparison with traffic on the fixed state (another ~6 min).

> Block V — closing the course. Before you start, review `00-theory.md` "USE and RED" and your notes from the
> mini-incidents.

## Goal
After a deployment of "minor configuration tweaks and code cleanup", the claims assistant misbehaves on several
fronts at once. Your task is to diagnose the incident **without reading the code** — only from telemetry (Tempo,
Prometheus, Pyroscope), `/diag`, the mock's `/admin/stats` and `Server-Timing` headers — and to write a chain for
every defect: **symptom → evidence (where and what number) → cause → fix**. The incident contains several
independent defects; each has its own distinguishable signal (verified by measurement on the same traffic).

## Theory in a nutshell
- **Several flaws at once** — symptoms overlap: one flaw can widen the window of another (e.g. a longer wait →
  a wider window of cache misses), and a shared symptom (slow responses, 503) has many possible causes. Look for a
  signal **specific** to the mechanism, not a generic "p99 is high".
- **Method** — RED per endpoint (which endpoint suffers and how: rate, errors by `outcome`, duration) → USE of the
  resources (slots: `llm_inflight`/`llm_waiting`; provider: `mock_llm_generating`, `mock_llm_cancelled_total`) →
  traces of specific requests (where the time goes) → hypothesis → test the hypothesis with one targeted command.
- **Backlog after the traffic** — what happens AFTER the end of inflow (ex. 10, 12): do the slots and the provider
  return to zero, and after how many seconds?
- Measurement pitfall: `status 0` in k6 with hundreds of new connections from a container to
  `host.docker.internal` is usually a Docker Desktop network `dial: i/o timeout`, not a response from the app (the
  app does not record them) — count them separately. The analyses in this traffic deliberately give up after 30 s
  (a client with a short timeout).

## Steps
1. Stop your own app (Ctrl+C) and the queue worker, if it is running. Start the incident:
   ```bash
   ./incident.sh start final
   curl -s 127.0.0.1:8060/health
   ```
2. **Initial hypothesis:** from the description ("minor configuration tweaks and code cleanup") write down the
   three things you will check first, and the metric for each.
3. Incident traffic (open model, ~4 min: summaries 8/s, streamed replies 1/s, FAQ 5/s — 5 popular questions,
   analyses 6/min with a client that gives up after 30 s). After the end of inflow, k6 waits up to 150 s for
   in-flight requests:
   ```bash
   ./incident.sh traffic
   ```
   **During the run** (Grafana → Explore → Prometheus, "Last 15 minutes") watch at least:
   ```
   sum by (endpoint, outcome) (rate(app_requests_total[1m]))
   max by (request_class) (llm_inflight)
   max by (request_class) (llm_waiting)
   max(mock_llm_generating)
   ```
   **After the end of inflow:** do `llm_inflight{request_class="long"}` and `mock_llm_generating` drop to 0 right away?
4. Diagnosis — for each area look for a signal and write down the number (there are no hints about which flaws are
   inside):
   - slot wait vs call time (ex. 01, 03, 06): the `llm_queue_wait_seconds` histogram per class, traces matching
     `{span.llm.queue.wait_ms > 100.0}` (the attribute is a float — `> 100` without `.0` finds nothing);
   - the stream from the client's side vs the provider's side (ex. 13): `app_stream_first_chunk_seconds` vs
     `llm_ttft_seconds`;
   - FAQ and cache (ex. 15): `sum by (outcome) (increase(app_cache_total[5m]))` vs the number of LLM calls for FAQ;
   - abandoned requests and wasted work (ex. 10, 12): `sum by (phase) (increase(mock_llm_cancelled_total[10m]))`,
     `curl -s 127.0.0.1:8061/admin/stats`, `curl -s 127.0.0.1:8060/diag`;
   - retries, limits, circuit breaker, event loop — rule them out with a number (e.g. `llm_http_attempts_total` /
     requests, `app_event_loop_lag_seconds`), not a guess.
   Verify hypotheses with the targeted commands from the exercises (e.g. 50 identical FAQ questions from ex. 15,
   `python scripts/stream_ttft.py -n 20 -c 5` from ex. 13) — during the incident, without reading the code.
5. `python check.py ex18` — on the incident it FAILs with a number for every unmet probe (the probes of the
   exercises that the defects concern). Save the messages — they are extra confirmation of your diagnosis, not a
   substitute for it.
6. **Report** (in a text file, for every defect): symptom → evidence (metric/query + number, trace in Tempo) →
   cause (the mechanism, not a file name) → fix (what to change and which command will prove that it helped).
   Add: what you ruled out and on what basis; how the defects affect each other.
7. **Fix and proof.** `./incident.sh stop`, start **your own** app (the state after ex. 17, with your fixes and
   without the "configuration tweaks" from the incident), then:
   ```bash
   python check.py ex18
   ```
   PASS = none of the incident's defects occurs in your version. To compare the numbers, run the same traffic on
   the reference state: `./incident.sh start custom 17 && ./incident.sh traffic`, then `./incident.sh stop`, and put
   both series of signals in one table.
8. Compare your report with `solutions/ex18_answers.md` and grade yourself with the rubric at the end of that file.

## Done criteria
- [ ] The report identifies every defect of the incident with a distinguishable signal (a number from
      Prometheus/Tempo/the mock) and a cause at the level of the mechanism.
- [ ] For at least two areas you have a documented exclusion (e.g. "there is no retry storm, because …").
- [ ] You can name one pair of defects that amplify each other's symptoms, and explain why.
- [ ] `python check.py ex18`: FAIL on the incident, PASS on your app.

## Review questions
1. Some of the summaries got a 503 after ~5 s, although the provider was underloaded. How do you tell "the queue
   has a limit and works correctly" from "too few slots"? Which metric do you show the team?
2. Why did the k6 report (`http_req_waiting`) not point to a problem with the stream?
3. After the end of inflow the mock was still generating for ~2 minutes. Who pays for that work, and how do you
   show it with a number?

Answers: `solutions/questions_answers.md` and `solutions/ex18_answers.md` (the full key + rubric).

## ★ Bonus (optional)
Write alerts (PromQL) that would detect each of the defects within 5 minutes of the deployment — with no false
alarms on the reference state. Test them on both runs from step 7.

---
Stuck? `solutions/hints/ex18_hint1.md` → `hint2` → `hint3`. The full key: `solutions/ex18_answers.md`
(only after you have written your own report).
