"""The SYNCHRONOUS variant (WSGI) for comparing gunicorn process models — ex. 07.

This is a proper WSGI app (not FastAPI run as WSGI): one thread = one request,
a synchronous anthropic client. Run:  gunicorn -c gunicorn.conf.py        (port 8062)

Endpoints (the same shapes as in app.main):
  GET  /health
  POST /claims/{n}/summary     summary (short, ~1.3 s on the mock)
  POST /claims/{n}/reply       reply to the customer (longer, ~3.3 s on the mock)
"""
from __future__ import annotations

import json
import os
import re
import time

import anthropic

from . import config, data

_client = anthropic.Anthropic(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY, max_retries=0,
                              timeout=anthropic.Timeout(connect=2.0, read=330.0, write=10.0, pool=5.0))
_ROUTE = re.compile(r"^/claims/(\d+)/(summary|reply)$")
_MAX_TOKENS = {"summary": 200, "reply": 700}
_HEADERS = {h: "HTTP_" + h.upper().replace("-", "_") for h in config.MOCK_HEADER_NAMES}


def _json(start_response, status: str, obj: dict, extra: list | None = None):
    body = json.dumps(obj, ensure_ascii=False).encode()
    start_response(status, [("content-type", "application/json"), ("content-length", str(len(body)))] + (extra or []))
    return [body]


def app(environ, start_response):
    path = environ.get("PATH_INFO", "")
    if path == "/health":
        return _json(start_response, "200 OK", {"status": "ok", "server": "gunicorn-wsgi",
                                                "pid": os.getpid()})
    m = _ROUTE.match(path)
    if not m or environ.get("REQUEST_METHOD") != "POST":
        return _json(start_response, "404 Not Found", {"error": "no such path"})
    n, kind = int(m.group(1)), m.group(2)
    headers = {h: environ[k] for h, k in _HEADERS.items() if k in environ}
    t0 = time.perf_counter()
    try:
        r = _client.messages.create(model=config.LLM_MODEL, max_tokens=_MAX_TOKENS[kind], extra_headers=headers or None,
                                    messages=[{"role": "user", "content": data.describe_for_llm(data.claim(n))}])
    except anthropic.APIError as e:
        return _json(start_response, "502 Bad Gateway", {"error": type(e).__name__})
    dur = (time.perf_counter() - t0) * 1000
    return _json(start_response, "200 OK", {"claim": data.claim(n)["id"], "tokens": r.usage.output_tokens},
                 [("server-timing", f"llm;dur={dur:.1f}, total;dur={dur:.1f}")])
