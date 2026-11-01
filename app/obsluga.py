"""Ścieżka żądania LLM: dopuszczenie → slot → deadline → ponowienia → fallback → klient.

Moduł infrastruktury — działa od startu. Tematy ćwiczeń żyją w modułach, które tu spinamy
(app/przeciazenie.py, app/llm/{limiter,wywolanie,ponowienia,fallback,klient}.py).

Dla każdego żądania zapisuje: wynik (`app.requests`), czas end-to-end (`app.request.duration`),
czas obsługi LLM (`llm.call.duration`) oraz nagłówek odpowiedzi
`Server-Timing: czekanie;dur=…, llm;dur=…, ttft;dur=…, total;dur=…` (ms) — czyta go k6 i check.py.
"""
from __future__ import annotations

import asyncio
import time

import anthropic
import httpx2
from fastapi import Request
from opentelemetry import trace

from . import config, przeciazenie, stan, telemetry
from .bledy import Anulowane, Odrzucone, Przeterminowane
from .llm import Wynik, Zadanie, fallback, limiter, ponowienia, wywolanie


def naglowki_atrapy(request: Request | None) -> dict:
    """Przekazuje x-mock-* z żądania klienta do atrapy (powtarzalne czasy odpowiedzi w testach)."""
    if request is None or not config.MOCK_HEADERS:
        return {}
    return {h: request.headers[h] for h in config.NAGLOWKI_ATRAPY if h in request.headers}


def klasyfikuj_wyjatek(e: BaseException) -> str:
    if isinstance(e, Odrzucone):
        return "odrzucone"
    if isinstance(e, Przeterminowane):
        return "przeterminowane"
    if isinstance(e, (Anulowane, asyncio.CancelledError)):
        return "anulowane"
    if isinstance(e, anthropic.RateLimitError):
        return "limit_dostawcy"
    if isinstance(e, (anthropic.APITimeoutError, httpx2.TimeoutException, TimeoutError)):
        return "timeout_dostawcy"
    if isinstance(e, (anthropic.APIError, httpx2.HTTPError)):
        return "blad_dostawcy"
    return "blad"


def zapisz_wynik(request: Request | None, endpoint: str, klasa: str, wynik: str, t0: float, czasy: dict) -> None:
    total = time.perf_counter() - t0
    czasy["total"] = total
    stan.WYNIKI[(endpoint, klasa, wynik)] += 1
    telemetry.zapisz(telemetry.C_ZADANIA, 1, endpoint=endpoint, klasa=klasa, wynik=wynik)
    telemetry.zapisz(telemetry.H_ZADANIE, total, endpoint=endpoint, klasa=klasa, wynik=wynik)
    span = trace.get_current_span()
    span.set_attribute("app.klasa", klasa)
    span.set_attribute("app.wynik", wynik)
    if request is not None:
        request.state.czasy = czasy


async def wykonaj(request: Request | None, z: Zadanie) -> Wynik:
    """Wykonuje zadanie LLM całą ścieżką; rzuca wyjątki mapowane na HTTP w app/main.py."""
    t0 = time.perf_counter()
    czasy: dict = {}
    wynik = "ok"
    try:
        przeciazenie.dopusc(z.klasa)
        async with limiter.slot(z.klasa, z.max_tokens, przeciazenie.max_czekania(z.klasa)) as czekanie:
            czasy["czekanie"] = czekanie
            t1 = time.perf_counter()
            dostawca = "?"
            wynik_llm = "ok"
            try:
                with telemetry.tracer.start_as_current_span("llm.call", attributes={"app.klasa": z.klasa}) as s:
                    w = await wywolanie.z_deadlinem(
                        request, z.klasa, lambda: ponowienia.z_ponowieniami(lambda: fallback.wywolaj(z)))
                    dostawca = w.dostawca
                    s.set_attribute("llm.dostawca", w.dostawca)
                    s.set_attribute("gen_ai.usage.output_tokens", w.tokeny_wyj)
            except BaseException as e:
                wynik_llm = klasyfikuj_wyjatek(e)
                raise
            finally:
                czasy["llm"] = time.perf_counter() - t1
                telemetry.zapisz(telemetry.H_WYWOLANIE, czasy["llm"], klasa=z.klasa, dostawca=dostawca,
                                 wynik=wynik_llm)
            if w.ttft_s is not None:
                czasy["ttft"] = w.ttft_s
                telemetry.zapisz(telemetry.H_TTFT, w.ttft_s, klasa=z.klasa)
        return w
    except BaseException as e:
        wynik = klasyfikuj_wyjatek(e)
        raise
    finally:
        zapisz_wynik(request, z.endpoint, z.klasa, wynik, t0, czasy)


def server_timing(czasy: dict | None) -> str | None:
    if not czasy:
        return None
    return ", ".join(f"{k};dur={v * 1000:.1f}" for k, v in czasy.items() if v is not None)
