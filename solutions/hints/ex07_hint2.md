# Ćw. 07 — podpowiedź 2 (konfiguracja)

W `gunicorn.conf.py`:
- `worker_class = "uvicorn_worker.UvicornWorker"` (ASGI, `app.main:app`, nie WSGI `app/wsgi.py`);
- `workers` wg rdzeni potrzebnych na CPU (tu 2), nie 2×CPU+1;
- `raw_env` z `LLM_SLOTY` **per proces** (2 procesy × 32 = 64 = moc dostawcy);
- dla workerów asynchronicznych `timeout` dotyczy heartbeat procesu, nie długości żądania.
Weryfikacja: `curl 127.0.0.1:8062/health` → `"serwer": "gunicorn-uvicorn"`, RSS procesów (`ps`), żądanie 90 s.
