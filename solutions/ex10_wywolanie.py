"""[ROZWIĄZANIE ćw. 10 — kopiuj do app/llm/wywolanie.py] Wywołanie LLM z deadline'em i anulowaniem.

Ćw. 10 ✅ (W6, W16):
- deadline CAŁKOWITY per klasa (`asyncio.timeout`) — niezależny od timeoutów SDK, które są per operacja;
  po przekroczeniu zadanie jest anulowane: połączenie z dostawcą się zamyka, a dostawca przerywa generację;
- strażnik rozłączenia: co 0.5 s `request.is_disconnected()`; gdy klient zniknął — anulujemy wywołanie,
  slot semafora i slot u dostawcy wracają od razu, zamiast po minutach generowania „do nikogo".
"""
from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import Awaitable, Callable

from fastapi import Request

from ..bledy import Anulowane, Przeterminowane

# Krótkie: SLO odpowiedzi rzędu sekund → 30 s to granica „i tak bezużyteczne".
# Długie: ogon 60–300 s (wymaganie) + zapas na czekanie u dostawcy → 330 s; k6/proxy muszą mieć więcej.
DEADLINE_S = {"krotkie": float(os.environ.get("DEADLINE_KROTKIE_S", "30")),
              "dlugie": float(os.environ.get("DEADLINE_DLUGIE_S", "330"))}


async def _czekaj_na_rozlaczenie(request: Request) -> None:
    while not await request.is_disconnected():
        await asyncio.sleep(0.5)


async def z_deadlinem(request: Request | None, klasa: str, fn: Callable[[], Awaitable]):
    deadline = DEADLINE_S[klasa]
    praca = asyncio.ensure_future(fn())
    straz = asyncio.ensure_future(_czekaj_na_rozlaczenie(request)) if request is not None else None
    try:
        async with asyncio.timeout(deadline):
            await asyncio.wait({praca} | ({straz} if straz else set()), return_when=asyncio.FIRST_COMPLETED)
    except TimeoutError:
        praca.cancel()
        with contextlib.suppress(BaseException):
            await praca
        raise Przeterminowane("wywołanie LLM", deadline) from None
    except asyncio.CancelledError:
        praca.cancel()
        raise
    finally:
        if straz is not None:
            straz.cancel()
    if praca.done():
        return praca.result()
    praca.cancel()                       # klient się rozłączył
    with contextlib.suppress(BaseException):
        await praca
    raise Anulowane()
