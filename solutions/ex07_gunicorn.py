# [ROZWIĄZANIE ćw. 07 — kopiuj do gunicorn.conf.py] Konfiguracja gunicorna — port 8062.
# Uruchom:  gunicorn -c gunicorn.conf.py
#
# ćw. 07 (W13) ✅: aplikacja jest I/O-bound (czeka na LLM), więc model procesów wybieramy wg
# WSPÓŁBIEŻNOŚCI, nie wg CPU:
#   - worker_class = UvicornWorker: jeden proces obsługuje setki żądań naraz (asyncio), uruchamia
#     aplikację ASGI app.main (ta sama co na 8060 — limiter, deadline'y, telemetria);
#   - workers = kilka (2) — po to, by wykorzystać więcej niż jeden rdzeń na CPU (JSON, TLS, telemetria)
#     i przetrwać awarię procesu; NIE po to, by zwiększyć liczbę równoległych wywołań LLM;
#   - semafor slotów jest PER PROCES: LLM_SLOTY=32 na proces × 2 = 64 = moc atrapy (sumę trzymaj ≤ mocy/limitu
#     dostawcy; gunicorn nie gwarantuje równego podziału połączeń między procesy, limit globalny wymagałby
#     np. semafora w Redisie);
#   - timeout: dla UvicornWorker to limit heartbeatu procesu (pętla zablokowana > timeout → restart),
#     a nie czasu żądania — wielominutowe wywołania LLM go nie wyzwalają (zmierzone w ćw. 07).
import os

wsgi_app = "app.main:app"
worker_class = "uvicorn_worker.UvicornWorker"
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
bind = f"127.0.0.1:{os.environ.get('APP_GUNICORN_PORT', '8062')}"
timeout = 30
graceful_timeout = 30
raw_env = ["APP_WARIANT=gunicorn-uvicorn", f"LLM_SLOTY={os.environ.get('LLM_SLOTY_NA_PROCES', '32')}"]
