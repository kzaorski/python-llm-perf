# Konfiguracja gunicorna — wariant porównawczy na porcie 8062 (ćw. 07).
# Uruchom:  gunicorn -c gunicorn.conf.py
#
# W13 (ćw. 07): model procesów skopiowany z poradnika dla aplikacji CPU-bound:
#   workery synchroniczne, liczba = 2 × CPU + 1. Każdy worker obsługuje JEDNO żądanie naraz,
#   więc przepustowość = workers / czas_wywołania_LLM, a żądania ponad to czekają w backlogu gniazda.
#   Domyślny --timeout 30 s zabija worker, który czeka na LLM dłużej (WORKER TIMEOUT → 500).
import multiprocessing
import os

wsgi_app = "app.wsgi:app"
worker_class = "sync"
workers = multiprocessing.cpu_count() * 2 + 1
bind = f"127.0.0.1:{os.environ.get('APP_GUNICORN_PORT', '8062')}"
timeout = 30
raw_env = ["APP_WARIANT=gunicorn-sync"]
