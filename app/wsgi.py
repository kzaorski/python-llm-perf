"""Wariant SYNCHRONICZNY (WSGI) do porównania modeli procesów gunicorna — ćw. 07.

To prawidłowa aplikacja WSGI (nie FastAPI uruchomione jako WSGI): jeden wątek = jedno żądanie,
synchroniczny klient anthropic. Uruchom:  gunicorn -c gunicorn.conf.py        (port 8062)

Endpointy (te same kształty co w app.main):
  GET  /health
  POST /claims/{n}/summary     streszczenie (krótkie, ~1.3 s u atrapy)
  POST /claims/{n}/reply       odpowiedź do klienta (dłuższa, ~3.3 s u atrapy)
"""
from __future__ import annotations

import json
import os
import re
import time

import anthropic

from . import config, dane

_klient = anthropic.Anthropic(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY, max_retries=0,
                              timeout=anthropic.Timeout(connect=2.0, read=330.0, write=10.0, pool=5.0))
_TRASA = re.compile(r"^/claims/(\d+)/(summary|reply)$")
_MAX = {"summary": 200, "reply": 700}
_NAGLOWKI = {h: "HTTP_" + h.upper().replace("-", "_") for h in config.NAGLOWKI_ATRAPY}


def _json(start_response, status: str, obj: dict, extra: list | None = None):
    body = json.dumps(obj, ensure_ascii=False).encode()
    start_response(status, [("content-type", "application/json"), ("content-length", str(len(body)))] + (extra or []))
    return [body]


def app(environ, start_response):
    path = environ.get("PATH_INFO", "")
    if path == "/health":
        return _json(start_response, "200 OK", {"status": "ok", "serwer": "gunicorn-wsgi",
                                                "pid": os.getpid()})
    m = _TRASA.match(path)
    if not m or environ.get("REQUEST_METHOD") != "POST":
        return _json(start_response, "404 Not Found", {"blad": "nie ma takiej ścieżki"})
    n, rodzaj = int(m.group(1)), m.group(2)
    naglowki = {h: environ[k] for h, k in _NAGLOWKI.items() if k in environ}
    t0 = time.perf_counter()
    try:
        r = _klient.messages.create(model=config.LLM_MODEL, max_tokens=_MAX[rodzaj], extra_headers=naglowki or None,
                                    messages=[{"role": "user", "content": dane.opis_dla_llm(dane.zgloszenie(n))}])
    except anthropic.APIError as e:
        return _json(start_response, "502 Bad Gateway", {"blad": type(e).__name__})
    dur = (time.perf_counter() - t0) * 1000
    return _json(start_response, "200 OK", {"zgloszenie": dane.zgloszenie(n)["id"], "tokeny": r.usage.output_tokens},
                 [("server-timing", f"llm;dur={dur:.1f}, total;dur={dur:.1f}")])
