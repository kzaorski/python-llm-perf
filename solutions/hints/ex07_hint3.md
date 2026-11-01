# Ćw. 07 — podpowiedź 3 (pseudokod)

```python
bind = "127.0.0.1:8062"
wsgi_app = "app.main:app"
worker_class = "uvicorn_worker.UvicornWorker"
workers = 2
raw_env = ["APP_WARIANT=gunicorn-uvicorn", "LLM_SLOTY=32"]   # per proces
```
Porównaj z `solutions/ex07_gunicorn.py` (nazwy zmiennych i reszta pliku). `python check.py ex07`.
