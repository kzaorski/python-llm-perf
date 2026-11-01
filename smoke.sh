#!/usr/bin/env bash
# smoke.sh — regresja kursu na ROZWIĄZANIACH, bez ruszania Twojego app/ (nakładka w .run/smoke-*).
#
#   ./smoke.sh            # pełny: k6 ćw. 02/03 na stanie z tamtych ćwiczeń + check.py --all na stanie końcowym
#   ./smoke.sh szybki     # tylko check.py --all na stanie końcowym (bez k6; ćw. 02/03 użyją starych wyników)
#
# Wymaga: `docker compose up -d --wait` (stos llmperf), .venv z requirements.txt, wolnych portów 8060/8062/8063
# (zatrzymaj własną aplikację, gunicorna, worker i eksporter metryk kolejki). Czas: ~6 min (szybki: ~4 min).
# Na koniec zatrzymuje wszystko, co uruchomił, i resetuje atrapę.
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
BIN=.venv/bin
TRYB=${1:-pelny}
mkdir -p .run/logs wyniki
PIDS=()

potomkowie() {  # pid → pid i wszyscy jego potomkowie (najpierw dzieci)
  local d
  for d in $(pgrep -P "$1" 2>/dev/null); do potomkowie "$d"; done
  echo "$1"
}

sprzatnij() {
  # taskiq worker (multiprocessing spawn) i gunicorn mają procesy potomne: zabicie samego mastera zostawia
  # sieroty, które dalej konsumują kolejkę ze starą konfiguracją — dlatego zbieramy całe drzewo procesów.
  local wszystkie=() p
  for p in "${PIDS[@]:-}"; do [ -n "$p" ] && wszystkie+=($(potomkowie "$p")); done
  for p in "${wszystkie[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null || true; done
  for _ in $(seq 1 25); do
    local zyje=0
    for p in "${wszystkie[@]:-}"; do [ -n "$p" ] && kill -0 "$p" 2>/dev/null && zyje=1; done
    [ "$zyje" = 0 ] && break; sleep 0.2
  done
  for p in "${wszystkie[@]:-}"; do [ -n "$p" ] && kill -9 "$p" 2>/dev/null || true; done
  curl -s -X POST 127.0.0.1:8061/admin/reset >/dev/null || true
}
trap sprzatnij EXIT

for port in 8060 8062 8063; do
  if lsof -tiTCP:$port -sTCP:LISTEN >/dev/null 2>&1; then
    echo "port $port zajęty — zatrzymaj to, co na nim działa (np. własną aplikację), i uruchom ponownie"; exit 2
  fi
done
curl -fsS 127.0.0.1:8061/health >/dev/null || { echo "atrapa LLM nie działa — docker compose up -d --wait"; exit 2; }
curl -fsS -u admin:admin 127.0.0.1:3060/api/health >/dev/null || { echo "Grafana/LGTM nie działa"; exit 2; }

czekaj_na() {  # url
  for _ in $(seq 1 100); do curl -fsS "$1" >/dev/null 2>&1 && return 0; sleep 0.2; done
  echo "nie wstało: $1"; return 1
}

uruchom_app() {  # do  → aplikacja z nakładki na 8060
  local cel=.run/smoke-$1
  $PY scripts/nakladka.py --do "$1" --cel "$cel" >/dev/null
  (cd "$cel" && exec ../../$BIN/uvicorn app.main:app --port 8060 --no-access-log) > .run/logs/smoke-app-$1.log 2>&1 &
  APP_PID=$!
  PIDS+=("$APP_PID")
  czekaj_na http://127.0.0.1:8060/diag/ping
}

zatrzymaj_app() { kill "$APP_PID" 2>/dev/null || true; wait "$APP_PID" 2>/dev/null || true; }

if [ "$TRYB" != "szybki" ]; then
  echo "== ćw. 02: model zamknięty vs otwarty (stan po ćw. 01: 4 sloty)"
  uruchom_app 1
  docker compose run --rm -e WYNIK=ex02-zamkniety k6 run -q -o experimental-prometheus-rw /scripts/zamkniety.js -e VUS=4 -e PAUZA_S=1 -e CZAS=40s | tail -12
  docker compose run --rm -e WYNIK=ex02-otwarty k6 run -q -o experimental-prometheus-rw /solutions/ex02_otwarty.js -e RATE=4 -e CZAS=40s | tail -12
  zatrzymaj_app
  echo "== ćw. 03: rampa (stan po ćw. 06)"
  uruchom_app 6
  docker compose run --rm -e WYNIK=ex03-rampa k6 run -q -o experimental-prometheus-rw /scripts/rampa.js -e OD=4 -e DO=28 -e SKOK=8 -e KROK_S=15 | tail -12
  zatrzymaj_app
fi

echo "== stan końcowy (wszystkie rozwiązania): aplikacja 8060, gunicorn 8062, worker + metryki kolejki 8063"
uruchom_app 18
(cd .run/smoke-18 && exec ../../$BIN/gunicorn -c gunicorn.conf.py) > .run/logs/smoke-gunicorn.log 2>&1 &
PIDS+=("$!")
(cd .run/smoke-18 && exec ../../$BIN/taskiq worker app.zadania:broker --workers 2 --max-async-tasks 4) > .run/logs/smoke-worker.log 2>&1 &
PIDS+=("$!")
(cd .run/smoke-18 && exec ../../$PY -m app.kolejka_metryki) > .run/logs/smoke-kolejka.log 2>&1 &
PIDS+=("$!")
czekaj_na http://127.0.0.1:8062/health
czekaj_na http://127.0.0.1:8063/metrics
sleep 3
$PY check.py --all
