# gunicorn configuration — the comparison variant on port 8062 (ex. 07).
# Run:  gunicorn -c gunicorn.conf.py
#
# F13 (ex. 07): a process model copied from a guide for CPU-bound apps:
#   sync workers, count = 2 × CPU + 1. Each worker serves ONE request at a time,
#   so throughput = workers / LLM_call_time, and requests beyond that wait in the socket backlog.
#   The default --timeout 30 s kills a worker that waits for the LLM longer (WORKER TIMEOUT → 500).
import multiprocessing
import os

wsgi_app = "app.wsgi:app"
worker_class = "sync"
workers = multiprocessing.cpu_count() * 2 + 1
bind = f"127.0.0.1:{os.environ.get('APP_GUNICORN_PORT', '8062')}"
timeout = 30
raw_env = ["APP_VARIANT=gunicorn-sync"]
