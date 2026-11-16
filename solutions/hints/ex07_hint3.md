# Ex. 07 — hint 3 (pseudocode)

```python
bind = "127.0.0.1:8062"
wsgi_app = "app.main:app"
worker_class = "uvicorn_worker.UvicornWorker"
workers = 2
raw_env = ["APP_VARIANT=gunicorn-uvicorn", "LLM_SLOTS=32"]   # per process
```
Compare with `solutions/ex07_gunicorn.py` (variable names and the rest of the file). `python check.py ex07`.
