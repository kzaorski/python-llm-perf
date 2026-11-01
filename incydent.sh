#!/usr/bin/env bash
# incydent.sh — uruchamia aplikację w stanie „po wszystkich ćwiczeniach" z PRZYWRÓCONYMI wadami.
# Diagnozujesz przez Grafanę (Tempo / Prometheus) i /diag — NIE czytaj kodu w .run/incydent-*.
#
#   ./incydent.sh start final            # finał (ćw. 18): kilka wad naraz
#   ./incydent.sh start mini-II          # mini-incydenty po blokach: mini-I … mini-IV
#   ./incydent.sh start własny 12 W7     # dowolny stan: --do 12 z przywróconą W7
#   ./incydent.sh ruch                   # ruch incydentu (k6, ~4 min; model otwarty, krótkie + długie)
#   ./incydent.sh stop                   # zatrzymuje aplikację incydentu, resetuje atrapę
#
# Wymaga wolnego portu 8060 (zatrzymaj własną aplikację). Po `stop` uruchom znów swoją aplikację.
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
PIDF=.run/incydent.pid
mkdir -p .run/logs

# scenariusze: stan (--do), wady, profil atrapy
scenariusz() {
  case "$1" in
    final)   echo "17 W3,W9,W10,W16 domyslny" ;;
    mini-I)  echo "3 W3 domyslny" ;;
    mini-II) echo "7 W2 domyslny" ;;
    mini-III) echo "11 W5 przeciazenie" ;;
    mini-IV) echo "13 W18 domyslny" ;;
    *) echo "" ;;
  esac
}

case "${1:-}" in
  start)
    if lsof -tiTCP:8060 -sTCP:LISTEN >/dev/null 2>&1; then
      echo "port 8060 zajęty — zatrzymaj własną aplikację (Ctrl+C) i spróbuj ponownie"; exit 2
    fi
    if [ "${2:-}" = "własny" ] || [ "${2:-}" = "wlasny" ]; then
      DO=$3; WADY=${4:-}; PROFIL=${5:-domyslny}; NAZWA=wlasny
    else
      read -r DO WADY PROFIL <<<"$(scenariusz "${2:-final}")"
      NAZWA=${2:-final}
      [ -n "$DO" ] || { echo "nieznany scenariusz: ${2:-}"; exit 2; }
    fi
    CEL=.run/incydent-$NAZWA
    $PY scripts/nakladka.py --do "$DO" ${WADY:+--wady "$WADY"} --cel "$CEL" >/dev/null
    curl -s -X POST 127.0.0.1:8061/admin/reset >/dev/null
    curl -s -X POST "127.0.0.1:8061/admin/profile/$PROFIL" >/dev/null
    (cd "$CEL" && APP_WARIANT="incydent-$NAZWA" nohup ../../.venv/bin/uvicorn app.main:app --port 8060 --no-access-log \
      > ../logs/incydent.log 2>&1 & echo $! > ../incydent.pid)
    for _ in $(seq 1 100); do curl -fsS 127.0.0.1:8060/diag/ping >/dev/null 2>&1 && break; sleep 0.2; done
    echo "incydent '$NAZWA' działa na :8060 (pid $(cat $PIDF)). Teraz: ./incydent.sh ruch — i do Grafany: http://127.0.0.1:3060"
    ;;
  ruch)
    docker compose run --rm -e WYNIK=incydent k6 run -o experimental-prometheus-rw /scripts/incydent.js
    ;;
  stop)
    if [ -f "$PIDF" ]; then kill "$(cat $PIDF)" 2>/dev/null || true; rm -f "$PIDF"; fi
    curl -s -X POST 127.0.0.1:8061/admin/reset >/dev/null || true
    echo "incydent zatrzymany, atrapa zresetowana"
    ;;
  *)
    sed -n '2,12p' "$0"; exit 1 ;;
esac
