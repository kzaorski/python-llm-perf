"""Asystent biura obsługi zgłoszeń szkodowych — aplikacja FastAPI (port 8060).

Uruchom lokalnie:   uvicorn app.main:app --port 8060
Wariant gunicorn:   gunicorn -c gunicorn.conf.py   (ćw. 07; port 8062)

Endpointy (klasa żądania w nawiasie; krótkie = sekundy, długie = 60–300 s):
  POST /claims/{n}/summary          streszczenie zgłoszenia (krótkie)              — ćw. 01–03, 06, 08–12
  POST /claims/{n}/classify         klasyfikacja (krótkie)                         — ćw. 04 (app/klasyfikacja.py)
  POST /claims/{n}/letter           pismo z szablonu (krótkie)                     — ćw. 05 (app/szablony.py)
  POST /claims/{n}/reply/stream     odpowiedź do klienta strumieniem SSE (krótkie) — ćw. 13 (app/strumien.py)
  POST /claims/{n}/analysis         analiza dokumentacji szkody (DŁUGIE)           — ćw. 10, 12
  POST /claims/{n}/summary/async    streszczenie przez kolejkę zadań → {"zadanie": id} — ćw. 14 (app/zadania.py)
  GET  /jobs/{id}                   stan/wynik zadania z kolejki
  GET  /faq?q=…                     odpowiedź na częste pytanie, cache Redis       — ćw. 15 (app/cache.py)
  POST /claims/{n}/priority         priorytet zgłoszenia, wsadowo                  — ćw. 16 (app/wsad.py)
  GET  /health, GET /diag, GET /diag/ping

Nagłówki x-mock-ttft-ms / x-mock-total-s / x-mock-output-tokens z żądania trafiają do atrapy LLM
(powtarzalne czasy odpowiedzi w testach k6). Każda odpowiedź LLM ma nagłówek Server-Timing
(czekanie / llm / ttft / total w ms).
"""
from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager

import anthropic
import httpx2
import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import config, telemetry

telemetry.konfiguruj()

from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # noqa: E402

from . import cache, dane, klasyfikacja, obsluga, stan, strumien, szablony, wsad, zadania  # noqa: E402
from .bledy import Anulowane, NiezaimplementowaneTODO, Odrzucone, Przeterminowane  # noqa: E402
from .llm import Zadanie, klient  # noqa: E402

_redis = aioredis.from_url(config.REDIS_URL)
_http = httpx2.AsyncClient(timeout=2.0)
START = time.time()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    monitor = asyncio.create_task(telemetry.monitor_petli())
    await zadania.broker.startup()          # producent kolejki zadań (ćw. 14)
    try:
        yield
    finally:
        monitor.cancel()
        await zadania.broker.shutdown()


app = FastAPI(title="claims-assistant (python-llm-perf)", version="1.0", lifespan=lifespan)
for r in (klasyfikacja.router, szablony.router, strumien.router, cache.router, wsad.router):
    app.include_router(r)


class ServerTiming:
    """Czyste middleware ASGI: dokleja Server-Timing z request.state.czasy (scope["state"]).

    Celowo NIE @app.middleware("http") (BaseHTTPMiddleware): ono podmienia `receive`, przez co
    `request.is_disconnected()` w handlerze nie widzi rozłączenia klienta (zmierzone w Bloku B).
    """

    def __init__(self, app_):
        self.app = app_

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def wyslij(msg):
            if msg["type"] == "http.response.start":
                st = obsluga.server_timing((scope.get("state") or {}).get("czasy"))
                naglowki = list(msg.get("headers", []))
                if st and not any(k.lower() == b"server-timing" for k, _ in naglowki):
                    naglowki.append((b"server-timing", st.encode()))
                    msg = {**msg, "headers": naglowki}
            await send(msg)
        await self.app(scope, receive, wyslij)


app.add_middleware(ServerTiming)


FastAPIInstrumentor.instrument_app(app, excluded_urls="/diag/ping")


# ---------------------------------------------------------------- błędy → HTTP
def _blad(request: Request, status: int, wynik: str, opis: str, headers: dict | None = None) -> JSONResponse:
    h = dict(headers or {})
    st = obsluga.server_timing(getattr(request.state, "czasy", None))
    if st:
        h["server-timing"] = st
    return JSONResponse({"wynik": wynik, "blad": opis}, status_code=status, headers=h)


@app.exception_handler(Odrzucone)
async def _odrzucone(request: Request, e: Odrzucone):
    return _blad(request, 503, "odrzucone", e.powod, {"retry-after": str(max(1, round(e.retry_after)))})


@app.exception_handler(Przeterminowane)
async def _przeterminowane(request: Request, e: Przeterminowane):
    return _blad(request, 504, "przeterminowane", str(e))


@app.exception_handler(Anulowane)
async def _anulowane(request: Request, e: Anulowane):
    return _blad(request, 499, "anulowane", "klient się rozłączył")


@app.exception_handler(NiezaimplementowaneTODO)
async def _todo(request: Request, e: NiezaimplementowaneTODO):
    return _blad(request, 501, "todo", f"Zrób najpierw ćwiczenie {e.cwiczenie}: {e.co}")


@app.exception_handler(anthropic.APIError)
async def _llm(request: Request, e: anthropic.APIError):
    wynik = obsluga.klasyfikuj_wyjatek(e)
    status = {"limit_dostawcy": 503, "timeout_dostawcy": 504}.get(wynik, 502)
    return _blad(request, status, wynik, f"{type(e).__name__}: {str(e)[:200]}")


@app.exception_handler(httpx2.HTTPError)
async def _http_err(request: Request, e: httpx2.HTTPError):
    wynik = obsluga.klasyfikuj_wyjatek(e)
    return _blad(request, 504 if wynik == "timeout_dostawcy" else 502, wynik, type(e).__name__)


# ---------------------------------------------------------------- endpointy domenowe
SYSTEM = "Jesteś asystentem likwidatora szkód w towarzystwie ubezpieczeniowym. Piszesz po polsku, rzeczowo."


@app.post("/claims/{n}/summary")
async def streszczenie(n: int, request: Request):
    z = dane.zgloszenie(n)
    w = await obsluga.wykonaj(request, Zadanie(
        klasa="krotkie", endpoint="summary", max_tokens=200, system=SYSTEM,
        prompt=f"Streść zgłoszenie dla likwidatora w 3 zdaniach.\n{dane.opis_dla_llm(z)}",
        naglowki=obsluga.naglowki_atrapy(request)))
    return {"zgloszenie": z["id"], "streszczenie": w.tekst, "dostawca": w.dostawca, "tokeny": w.tokeny_wyj}


@app.post("/claims/{n}/analysis")
async def analiza(n: int, request: Request):
    """Analiza całej dokumentacji szkody — wywołanie wielominutowe (klasa `dlugie`)."""
    z = dane.zgloszenie(n)
    w = await obsluga.wykonaj(request, Zadanie(
        klasa="dlugie", endpoint="analysis", max_tokens=4000, system=SYSTEM,
        prompt=f"Przeanalizuj pełną dokumentację szkody: zasadność, ryzyka, brakujące dokumenty, rekomendacja.\n"
               f"{dane.opis_dla_llm(z)}",
        naglowki=obsluga.naglowki_atrapy(request)))
    return {"zgloszenie": z["id"], "analiza_znaki": len(w.tekst), "dostawca": w.dostawca, "tokeny": w.tokeny_wyj}


@app.post("/claims/{n}/summary/async")
async def streszczenie_async(n: int, request: Request):
    t = await zadania.streszczenie_w_tle.kiq(n, obsluga.naglowki_atrapy(request), time.time())
    return {"zadanie": t.task_id}


@app.get("/jobs/{task_id}")
async def zadanie(task_id: str):
    if not await zadania.broker.result_backend.is_result_ready(task_id):
        return {"zadanie": task_id, "stan": "czeka_lub_w_toku"}
    r = await zadania.broker.result_backend.get_result(task_id)
    if r.is_err:
        return {"zadanie": task_id, "stan": "blad", "blad": str(r.error)[:200]}
    return {"zadanie": task_id, "stan": "gotowe", "wynik": r.return_value}


# ---------------------------------------------------------------- health / diagnostyka
async def _probe(coro) -> dict:
    t0 = time.perf_counter()
    try:
        await coro
        return {"ok": True, "ms": round((time.perf_counter() - t0) * 1000, 1)}
    except Exception as e:  # noqa: BLE001 — health raportuje, nie rzuca
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}


async def _llm_health():
    r = await _http.get(config.LLM_BASE_URL.rstrip("/") + "/health")
    r.raise_for_status()


@app.get("/health")
async def health():
    lokalny = "127.0.0.1" in config.LLM_BASE_URL or "localhost" in config.LLM_BASE_URL
    deps = {"redis": await _probe(_redis.ping()),
            "llm": await _probe(_llm_health()) if lokalny else {"ok": True, "skipped": "zewnętrzny dostawca"}}
    return {"status": "ok" if all(d["ok"] for d in deps.values()) else "degraded", "deps": deps,
            "serwer": telemetry.WARIANT, "pid": os.getpid(), "zgloszen": dane.liczba()}


@app.get("/diag/ping")
async def ping():
    """Bez I/O i bez telemetrii — czas odpowiedzi = responsywność pętli zdarzeń."""
    return {"ok": True}


@app.get("/diag")
async def diag():
    """Stan procesu: kolejka do LLM per klasa, lag pętli, wyniki i próby HTTP od startu, konfiguracja klientów."""
    def kl(k):
        t = k.timeout
        return {"max_retries": k.max_retries,
                "timeout": {"connect": t.connect, "read": t.read} if hasattr(t, "read") else t}
    return {
        "pid": os.getpid(), "serwer": telemetry.WARIANT, "uptime_s": round(time.time() - START, 1),
        "kolejka": {k: s.jako_dict() for k, s in stan.STAN.items()},
        "petla_lag_max_10s_ms": round(stan.PETLA.max_ostatnie() * 1000, 1),
        "wyniki": [{"endpoint": e, "klasa": k, "wynik": w, "n": n} for (e, k, w), n in sorted(stan.WYNIKI.items())],
        "proby_http": [{"dostawca": d, "status": s, "n": n} for (d, s), n in sorted(stan.PROBY_HTTP.items())],
        "klienci": {kl_: kl(klient.klient(kl_, "a")) for kl_ in stan.KLASY},
    }
