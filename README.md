# python-llm-perf course — a Python LLM application under load

A hands-on "learn-by-doing" course on the performance of applications that spend most of their time
**waiting**: for a language model's response, for a slot, for a provider limit, in a queue. You work on a claims
service desk assistant for an insurance company (FastAPI + asyncio + the Anthropic SDK), load it with k6 and
watch it in Grafana (Tempo, Prometheus, Pyroscope). The application starts with built-in flaws — finding,
measuring and fixing them is the content of the 18 exercises.
Instructions in English.

> Course verified 2026-11 on: Python 3.13.13, fastapi 0.162.0, starlette 1.10.0, uvicorn 0.54.0,
> gunicorn 26.2.0 + uvicorn-worker 0.4.0, anthropic 2.3.0 (httpx2 2.16.0), opentelemetry-sdk 1.45.2
> (instrumentations 0.66b2), pyroscope-io 1.4.0, taskiq 0.13.0 + taskiq-redis 1.2.4, redis-py 8.1.0,
> images `grafana/otel-lgtm:0.39.0`, `grafana/k6:2.3.0`, `redis:8.8.4-alpine`, mock LLM 1.1 (`python:3.13.18-slim-trixie`).
> Smoke test from scratch (2026-11-01, fresh clone, Docker Desktop on macOS, arm64): a fresh install on Python
> **3.11.17** (the lowest supported) and 3.13.13; the first `docker compose up -d --wait` on empty volumes ~10 s
> (images cached, no pulling), `pip install` + data ~20 s; ex. 01 and 12 (the 180 s runs A and B) executed
> literally — numbers match the tables; `check.py --all` on the skeleton: 17 × FAIL + SKIP ex17 (no exceptions,
> ~11 min); `./smoke.sh` on the solutions: 17 × PASS + SKIP ex17 (no key), ~7 min.

The emphasis is on theory and clear explanations of concepts — start with `exercises/00-theory.md`, read
`exercises/NNa-*.md` before the blocks, and look up definitions in `glossary.md` (entries with links to the
exercises).

## Prerequisites

- **You must know:** Python (asyncio at the `async`/`await` level), HTTP basics, running load tests (any tool),
  Docker and a terminal.
- **You do not need to know** (the course teaches it from scratch): queueing theory and Little's law, the open
  vs closed model in tests, asyncio internals (the loop, thread pools), OpenTelemetry/TraceQL/PromQL, k6, taskiq.
- **Hardware:** Docker (Docker Desktop on macOS works), ~4 GB of RAM for the containers, Python 3.11–3.14
  (the repo pins 3.13 in `.python-version`).
- **No LLM account is needed.** The whole course runs on a local mock compatible with the Messages API. An
  Anthropic key is useful only in the optional ex. 17 (cost ≈ $0.005).

## Architecture

```
  k6 (container, tools profile) ──HTTP──▶  FastAPI application  (local, :8060; gunicorn variant :8062)
       open / closed model                 │  semaphores/pools per class, rate limiter, retries,
                                           │  deadline + cancellation, circuit breaker, backpressure, cache, batches
                                           ├──Messages API──▶ mock LLM  (mock-llm container, :8061)
                                           │                  providers "a" and "b", limits, 429/529, SSE,
                                           │                  minute-long profiles (60–300 s), /admin/*
                                           ├──Redis Streams──▶ taskiq worker (local) + metrics exporter :8063
                                           ├──Redis :6460 (FAQ cache, task queue, results)
                                           └──OTLP/HTTP :4368, Pyroscope :4060──▶ grafana/otel-lgtm
                                                  Grafana :3060 (Tempo, Prometheus :9196, Pyroscope)
```

The application, gunicorn and the worker run **locally** — you edit the code and restart the process without
rebuilding an image. k6 reaches the host through `host.docker.internal`.

## Quick start

0. Your own branch for the work: `git switch -c my-exercises` — the exercises modify the application files; the
   branch you started from stays clean as a free reset, and `git diff <that branch>` will show everything you
   built at the end.
1. Build the local mock LLM image and start the stack (from the repository root):
   ```bash
   docker compose build mock-llm
   docker compose up -d --wait
   ```
   The `llmperf-mock-llm:1.1` image is built from the `mock_llm/` directory — it is not published on Docker
   Hub. On a new computer, run the build step first; skipping it may produce the message
   `pull access denied for llmperf-mock-llm`. Repeat the build after changing the mock's code or its Dockerfile.
   The stack (project `llmperf`): `lgtm`, `redis`, `mock-llm` →
   Grafana http://127.0.0.1:3060 (admin/admin).
2. Environment: `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
   (or `uv venv && uv pip install -r requirements.txt`).
3. Variables (optional — the defaults are in the code): `cp .env.example .env; set -a; source .env; set +a`.
4. Data: `python scripts/generate_claims.py` (20,000 claims → `data/`).
5. Application: `uvicorn app.main:app --port 8060`; check: `curl -s 127.0.0.1:8060/health`.
6. Start with `exercises/00-theory.md`, then `EXERCISES.md` → `exercises/01-first-trace.md`.

## Running and tools

| What | Command |
|---|---|
| application (the skeleton with flaws) | `uvicorn app.main:app --port 8060` |
| gunicorn variant (ex. 07) | `gunicorn -c gunicorn.conf.py` (:8062) |
| queue worker + metrics (ex. 14) | `taskiq worker app.tasks:broker --workers 2 --max-async-tasks 4` and `python -m app.queue_metrics` (:8063) |
| k6 traffic | `docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/<file>.js -e VARIABLE=…` → summary in `results/` |
| run with backlog sampling | `python scripts/measure.py <name> --inflow-s 180 -- run …` → `results/<name>-run.json` (backlog at the end of the inflow, drain) |
| client-side stream TTFT | `python scripts/stream_ttft.py -n 20 -c 5` |
| application state "after ex. NN" | `python scripts/overlay.py --after NN` → `uvicorn --app-dir .run/after-NN app.main:app --port 8060` |
| mock LLM | `curl -s 127.0.0.1:8061/admin/stats`, `POST /admin/profile/<name>`, `PATCH /admin/config?provider=a`, `POST /admin/reset` |
| application state | `curl -s 127.0.0.1:8060/diag` (queue per class, loop lag, outcomes, HTTP attempts, client timeouts) |
| "done" criteria | `python check.py exNN` / `python check.py --all` |
| mini-incidents and the final | `./incident.sh start mini-I|mini-II|mini-III|mini-IV|final`, `./incident.sh traffic`, `./incident.sh stop` |
| regression on the solutions | `./smoke.sh` (~7 min, needs free ports 8060/8062/8063) |

Stuck? First the graded hints in `solutions/hints/` (direction → API/metric → pseudocode), only then the
ready-made versions in `solutions/` (see `solutions/README.md`).

## Repo map

| Path | What it is |
|---|---|
| `app/` | the FastAPI application; `app/llm/` — client, limiter (slots, rate), retries, deadline/cancellation, fallback |
| `mock_llm/` | the mock LLM (image `llmperf-mock-llm:1.1`) |
| `k6/` | traffic scenarios (open, closed, ramp, mixed, long, stream, gunicorn, incident) |
| `scripts/` | data, state overlays, measurement with sampling, stream TTFT, comparison with Claude |
| `exercises/` | 18 exercises + `00-theory.md` + 5 block readings `NNa-*.md` |
| `EXERCISES.md` | the index of exercises, times, skills map |
| `glossary.md` | the glossary with links to the exercises |
| `solutions/` | cumulative solutions, hints, answers to the review questions, the final's answer key |
| `check.py`, `smoke.sh`, `incident.sh` | "done" verification, regression, incidents |
| `gunicorn.conf.py` | configuration of the gunicorn variant (ex. 07) |
| `docker-compose.yml`, `grafana/` | the observability stack, Redis, the mock, k6; dashboards and scrape config |
| `results/` | k6 and run summaries (not in the repo) |

## Notes

- **Time:** the exercises with mini-incidents ~16 h, the readings ~3.5 h. Ex. 10, 12 and 18 contain multi-minute
  tests (3–4 min inflow + drain) — that is intended: LLM calls lasting minutes are part of the course's subject.
- **Cost:** zero when working on the mock. The optional ex. 17 on the real Claude (`claude-haiku-5-5`, 24
  sequential calls) ≈ $0.005 — keep the key only in the current shell, never in the repo.
- **Ports** (all on 127.0.0.1): application 8060, mock LLM 8061, gunicorn 8062, worker metrics 8063,
  Grafana 3060, OTLP 4367 (gRPC) / 4368 (HTTP), Prometheus 9196, Pyroscope 4060, Redis 6460. They were chosen
  so as not to collide with other stacks you may have running; if something on your machine uses one of
  them, change the value in `.env` (compose reads `*_PORT`) and the matching addresses (`LLM_BASE_URL`,
  `REDIS_URL`, `OTEL_*`). Do not run several heavy observability stacks at once.
- **Known limitation: `dial: i/o timeout` in k6 (Docker Desktop).** The k6 container connects to the application
  on the host through `host.docker.internal`. With hundreds of NEW connections in a short time, Docker Desktop
  sometimes fails to establish some of them: in the k6 summary this is `status 0` (for example
  `status_short_0`), and in the k6 log `dial: i/o timeout`. Measured: 0.66% of requests in the ramp, ~4% in the
  240-second incident — in both variants (with flaws and fixed). How to tell it from an application flaw: the
  application **does not record** these requests (`app_requests_total` and `/diag` do not count them, no traces),
  they appear in a similar number before and after the fix, and they have no `Server-Timing`. An application
  flaw produces a response (503/504/502) or a trace with a long wait. Report `status 0` separately.
- **k6 and long requests:** k6 has a default 60 s request timeout and a 30 s `gracefulStop` — the course scripts set
  their own values (longer than the longest request), otherwise k6 cuts minute-long requests and falsifies the
  drain.
- **macOS:** ports 5000/7000 are taken by AirPlay — the course does not use them.
