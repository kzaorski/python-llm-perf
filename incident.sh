#!/usr/bin/env bash
# incident.sh — runs the app in the "after all exercises" state with the flaws RESTORED.
# You diagnose through Grafana (Tempo / Prometheus) and /diag — do NOT read the code in .run/incident-*.
#
#   ./incident.sh start final            # the final (ex. 18): several flaws at once
#   ./incident.sh start mini-II          # mini-incidents after the blocks: mini-I … mini-IV
#   ./incident.sh start custom 12 F7     # any state: --after 12 with F7 restored
#   ./incident.sh traffic                # incident traffic (k6, ~4 min; open model, short + long)
#   ./incident.sh stop                   # stops the incident app, resets the mock
#
# Requires free port 8060 (stop your own app). After `stop`, start your own app again.
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
PIDF=.run/incident.pid
mkdir -p .run/logs

# scenarios: the state (--after), flaws (modules rolled back to the version from before the fix; "-" = none), the mock profile, env
# (some flaws are configuration, not code — e.g. a pool that is too small: LLM_SLOTS=4 on the final state)
scenario() {
  case "$1" in
    final)    echo "17 F9,F10,F16 default LLM_SLOTS=4 FAQ_TTL_S=30" ;;
    mini-I)   echo "3 - default LLM_SLOTS=4" ;;
    mini-II)  echo "7 F2 default" ;;
    mini-III) echo "11 F5 overload" ;;
    mini-IV)  echo "13 F18 default" ;;
    *) echo "" ;;
  esac
}

case "${1:-}" in
  start)
    if lsof -tiTCP:8060 -sTCP:LISTEN >/dev/null 2>&1; then
      echo "port 8060 is in use — stop your own app (Ctrl+C) and try again"; exit 2
    fi
    if [ "${2:-}" = "custom" ]; then
      AFTER=$3; FLAWS=${4:-}; PROFILE=${5:-default}; NAME=custom
    else
      read -r AFTER FLAWS PROFILE ENVS <<<"$(scenario "${2:-final}")"
      [ "$FLAWS" = "-" ] && FLAWS=""
      NAME=${2:-final}
      [ -n "$AFTER" ] || { echo "unknown scenario: ${2:-}"; exit 2; }
    fi
    TARGET=.run/incident-$NAME
    $PY scripts/overlay.py --after "$AFTER" ${FLAWS:+--flaws "$FLAWS"} --target "$TARGET" >/dev/null
    curl -s -X POST 127.0.0.1:8061/admin/reset >/dev/null
    curl -s -X POST "127.0.0.1:8061/admin/profile/$PROFILE" >/dev/null
    (cd "$TARGET" && exec env ${ENVS:-} APP_VARIANT="incident-$NAME" ../../.venv/bin/uvicorn app.main:app --port 8060 \
      --no-access-log) > .run/logs/incident.log 2>&1 &
    echo $! > "$PIDF"
    for _ in $(seq 1 100); do curl -fsS 127.0.0.1:8060/diag/ping >/dev/null 2>&1 && break; sleep 0.2; done
    echo "incident '$NAME' is running on :8060 (pid $(cat $PIDF)). Now: ./incident.sh traffic — and go to Grafana: http://127.0.0.1:3060"
    ;;
  traffic)
    docker compose run --rm -e RESULT=incident k6 run -o experimental-prometheus-rw /scripts/incident.js
    ;;
  stop)
    if [ -f "$PIDF" ]; then
      P=$(cat "$PIDF")
      kill "$P" 2>/dev/null || true
      # after SIGTERM uvicorn waits for in-flight requests (in incidents they can last minutes) — after 5 s we force-kill it
      for _ in $(seq 1 25); do kill -0 "$P" 2>/dev/null || break; sleep 0.2; done
      kill -9 "$P" 2>/dev/null || true
      for _ in $(seq 1 25); do lsof -tiTCP:8060 -sTCP:LISTEN >/dev/null 2>&1 || break; sleep 0.2; done
      rm -f "$PIDF"
    fi
    curl -s -X POST 127.0.0.1:8061/admin/reset >/dev/null || true
    echo "incident stopped, the mock has been reset"
    ;;
  *)
    sed -n '2,12p' "$0"; exit 1 ;;
esac
