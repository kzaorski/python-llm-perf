# [SOLUTION ex. 07 — copy to gunicorn.conf.py] gunicorn configuration — port 8062.
# Run:  gunicorn -c gunicorn.conf.py
#
# ex. 07 (F13) ✅: the app is I/O-bound (it waits for the LLM), so we pick the process model by
# CONCURRENCY, not by CPU:
#   - worker_class = UvicornWorker: one process serves hundreds of requests at once (asyncio), and runs
#     the ASGI app app.main (the same as on 8060 — limiter, deadlines, telemetry);
#   - workers = a few (2) — to use more than one CPU core (JSON, TLS, telemetry)
#     and to survive a process crash; NOT to increase the number of parallel LLM calls;
#   - the slot semaphore is PER PROCESS: LLM_SLOTS=32 per process × 2 = 64 = the mock's capacity (keep the sum ≤ the provider's
#     capacity/limit; gunicorn does not guarantee an even split of connections between processes, a global limit would require
#     e.g. a semaphore in Redis);
#   - timeout: for UvicornWorker it is the process heartbeat limit (loop blocked > timeout → restart),
#     not a request time limit — multi-minute LLM calls do not trigger it (measured in ex. 07).
import os

wsgi_app = "app.main:app"
worker_class = "uvicorn_worker.UvicornWorker"
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
bind = f"127.0.0.1:{os.environ.get('APP_GUNICORN_PORT', '8062')}"
timeout = 30
graceful_timeout = 30
raw_env = ["APP_VARIANT=gunicorn-uvicorn", f"LLM_SLOTS={os.environ.get('LLM_SLOTS_PER_PROCESS', '32')}"]
