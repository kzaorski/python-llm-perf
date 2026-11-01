"""[ROZWIĄZANIE ćw. 13 — kopiuj do app/strumien.py] Odpowiedź do klienta strumieniem (SSE) — endpoint POST /claims/{n}/reply/stream.

Zdarzenia SSE: `event: delta` (fragment tekstu), na końcu `event: koniec` (statystyki), przy błędzie `event: blad`.

Ćw. 13 (W9): handler zbiera CAŁĄ odpowiedź LLM i dopiero potem wysyła ją klientowi jednym zdarzeniem.
Dostawca podaje pierwszy token po ~0.5 s, ale klient widzi pierwszy bajt po całej generacji (TTFT
klienta ≈ czas całkowity). Metryka `llm.ttft` (od strony dostawcy) wygląda dobrze — kłamie o UX.
✅ ćw. 13: fragmenty wysyłane od razu; rozłączenie klienta przerywa generację.
"""
from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from . import dane, obsluga, przeciazenie, telemetry
from .llm import Zadanie, klient, limiter

router = APIRouter()


def sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


def zadanie(n: int, request: Request) -> Zadanie:
    z = dane.zgloszenie(n)
    return Zadanie(klasa="krotkie", endpoint="reply-stream", max_tokens=700,
                   prompt=f"Napisz odpowiedź do klienta w sprawie zgłoszenia.\n{dane.opis_dla_llm(z)}",
                   naglowki=obsluga.naglowki_atrapy(request))


@router.post("/claims/{n}/reply/stream")
async def odpowiedz_strumieniem(n: int, request: Request):
    z = zadanie(n, request)

    async def generuj():
        t0 = time.perf_counter()
        czasy: dict = {}
        wynik = "ok"
        try:
            przeciazenie.dopusc(z.klasa)
            async with limiter.slot(z.klasa, z.max_tokens, przeciazenie.max_czekania(z.klasa)) as czekanie:
                czasy["czekanie"] = czekanie
                t1 = time.perf_counter()
                n_fragm = 0
                # ćw. 13 (W9) ✅: każdy fragment od razu do klienta — TTFT klienta ≈ TTFT dostawcy.
                async for tekst in klient.strumien(z):
                    if n_fragm == 0:
                        czasy["ttft"] = time.perf_counter() - t1
                        telemetry.zapisz(telemetry.H_TTFT, czasy["ttft"], klasa=z.klasa)
                    n_fragm += 1
                    yield sse("delta", {"tekst": tekst})
                    # Starlette (ASGI ≥ 2.4) nie przerwie generatora po rozłączeniu sama — sprawdzamy
                    if n_fragm % 20 == 0 and await request.is_disconnected():
                        wynik = "anulowane"
                        return
                czasy["llm"] = time.perf_counter() - t1
            yield sse("koniec", {k: round(v * 1000, 1) for k, v in czasy.items()})
        except (GeneratorExit, asyncio.CancelledError, OSError):
            wynik = "anulowane"     # klient się rozłączył
            raise
        except Exception as e:
            wynik = obsluga.klasyfikuj_wyjatek(e)
            yield sse("blad", {"wynik": wynik, "blad": type(e).__name__})
        finally:
            obsluga.zapisz_wynik(None, z.endpoint, z.klasa, wynik, t0, czasy)

    return StreamingResponse(generuj(), media_type="text/event-stream", headers={"cache-control": "no-cache"})
