# Ex. 07 — hint 2 (configuration)

In `gunicorn.conf.py`:
- `worker_class = "uvicorn_worker.UvicornWorker"` (ASGI, `app.main:app`, not the WSGI `app/wsgi.py`);
- `workers` based on the cores needed for CPU (here 2), not 2×CPU+1;
- `raw_env` with `LLM_SLOTS` **per process** (2 processes × 32 = 64 = the provider's capacity);
- for async workers `timeout` concerns the process heartbeat, not the request length.
Verification: `curl 127.0.0.1:8062/health` → `"server": "gunicorn-uvicorn"`, process RSS (`ps`), a 90 s request.
