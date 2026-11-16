#!/usr/bin/env bash
# smoke.sh — the course regression on the SOLUTIONS, without touching your app/ (the overlay in .run/smoke-*).
#
#   ./smoke.sh            # full: k6 ex. 02/03 on the state from those exercises + check.py --all on the final state
#   ./smoke.sh quick      # only check.py --all on the final state (no k6; ex. 02/03 will use the old results)
#
# Requires: `docker compose up -d --wait` (the llmperf stack), .venv with requirements.txt, free ports 8060/8062/8063
# (stop your own app, gunicorn, the worker and the queue metrics exporter). Time: ~7 min (quick: ~4 min).
# At the end it stops everything it started and resets the mock.
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
BIN=.venv/bin
MODE=${1:-full}
mkdir -p .run/logs results
PIDS=()

descendants() {  # pid → the pid and all its descendants (children first)
  local d
  for d in $(pgrep -P "$1" 2>/dev/null); do descendants "$d"; done
  echo "$1"
}

cleanup() {
  # the taskiq worker (multiprocessing spawn) and gunicorn have child processes: killing only the master leaves
  # orphans that keep consuming the queue with the old configuration — that is why we collect the whole process tree.
  local all_pids=() p
  for p in "${PIDS[@]:-}"; do [ -n "$p" ] && all_pids+=($(descendants "$p")); done
  for p in "${all_pids[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null || true; done
  for _ in $(seq 1 25); do
    local alive=0
    for p in "${all_pids[@]:-}"; do [ -n "$p" ] && kill -0 "$p" 2>/dev/null && alive=1; done
    [ "$alive" = 0 ] && break; sleep 0.2
  done
  for p in "${all_pids[@]:-}"; do [ -n "$p" ] && kill -9 "$p" 2>/dev/null || true; done
  curl -s -X POST 127.0.0.1:8061/admin/reset >/dev/null || true
}
trap cleanup EXIT

for port in 8060 8062 8063; do
  if lsof -tiTCP:$port -sTCP:LISTEN >/dev/null 2>&1; then
    echo "port $port is in use — stop whatever is running on it (e.g. your own app) and run again"; exit 2
  fi
done
curl -fsS 127.0.0.1:8061/health >/dev/null || { echo "the mock LLM is not running — docker compose up -d --wait"; exit 2; }
curl -fsS -u admin:admin 127.0.0.1:3060/api/health >/dev/null || { echo "Grafana/LGTM is not running"; exit 2; }

wait_for() {  # url
  for _ in $(seq 1 100); do curl -fsS "$1" >/dev/null 2>&1 && return 0; sleep 0.2; done
  echo "did not come up: $1"; return 1
}

start_app() {  # after  → the app from the overlay on 8060
  local target=.run/smoke-$1
  $PY scripts/overlay.py --after "$1" --target "$target" >/dev/null
  (cd "$target" && exec ../../$BIN/uvicorn app.main:app --port 8060 --no-access-log) > .run/logs/smoke-app-$1.log 2>&1 &
  APP_PID=$!
  PIDS+=("$APP_PID")
  wait_for http://127.0.0.1:8060/diag/ping
}

stop_app() { kill "$APP_PID" 2>/dev/null || true; wait "$APP_PID" 2>/dev/null || true; }

if [ "$MODE" != "quick" ]; then
  echo "== ex. 02: closed vs open model (the state after ex. 01: 4 slots)"
  start_app 1
  docker compose run --rm -e RESULT=ex02-closed k6 run -q -o experimental-prometheus-rw /scripts/closed_model.js -e VUS=4 -e PAUSE_S=1 -e DURATION=40s | tail -12
  docker compose run --rm -e RESULT=ex02-open k6 run -q -o experimental-prometheus-rw /solutions/ex02_open_model.js -e RATE=4 -e DURATION=40s | tail -12
  stop_app
  echo "== ex. 03: ramp (the state after ex. 06)"
  start_app 6
  docker compose run --rm -e RESULT=ex03-ramp k6 run -q -o experimental-prometheus-rw /scripts/ramp.js -e FROM=4 -e TO=28 -e STEP_RPS=8 -e STEP_S=15 | tail -12
  stop_app
fi

echo "== final state (all solutions): app 8060, gunicorn 8062, worker + queue metrics 8063"
start_app 18
(cd .run/smoke-18 && exec ../../$BIN/gunicorn -c gunicorn.conf.py) > .run/logs/smoke-gunicorn.log 2>&1 &
PIDS+=("$!")
(cd .run/smoke-18 && exec ../../$BIN/taskiq worker app.tasks:broker --workers 2 --max-async-tasks 4) > .run/logs/smoke-worker.log 2>&1 &
PIDS+=("$!")
(cd .run/smoke-18 && exec ../../$PY -m app.queue_metrics) > .run/logs/smoke-queue.log 2>&1 &
PIDS+=("$!")
wait_for http://127.0.0.1:8062/health
wait_for http://127.0.0.1:8063/metrics
sleep 3
$PY check.py --all
