"""Sloty LLM: ile wywołań naraz (semafor) i w jakim tempie (limiter dostawcy).

Ćw. 01 — TODO: pokaż czas czekania na slot w trace i w metrykach.
Ćw. 06 — rozmiar puli (W3): ile slotów potrzeba przy danym ruchu (prawo Little'a: L = λ·W).
Ćw. 08 — TODO: limiter tempa wobec limitów dostawcy (W4: teraz brak — lawina 429).
Ćw. 12 — osobne pule dla klas krótkich i długich (W18: teraz jedna wspólna pula).

`slot()` jest używany przez app/obsluga.py:
    async with limiter.slot(klasa, max_tokens, max_czekania):
        ... wywołanie LLM ...
"""
from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager

from .. import stan, telemetry
from ..bledy import Odrzucone

# W3 (ćw. 06): 4 sloty „na wszelki wypadek" — przy ~20 żądaniach/s i ~1.3 s na wywołanie za mało.
SLOTY = int(os.environ.get("LLM_SLOTY", "4"))
# W18 (ćw. 12): jedna pula dla krótkich i wielominutowych wywołań.
_SEMAFOR = asyncio.Semaphore(SLOTY)


def semafor(klasa: str) -> asyncio.Semaphore:
    return _SEMAFOR


@asynccontextmanager
async def slot(klasa: str, max_tokens: int, max_czekania: float | None = None):
    """Zajmuje slot LLM dla klasy; `max_czekania` (s) — po tym czasie Odrzucone (ćw. 12)."""
    st = stan.STAN[klasa]
    sem = semafor(klasa)
    tok = st.zacznij_czekac()
    t0 = time.perf_counter()
    t0_ns = time.time_ns()
    try:
        if max_czekania is None:
            await sem.acquire()
        else:
            try:
                await asyncio.wait_for(sem.acquire(), max_czekania)
            except TimeoutError:
                raise Odrzucone("czekanie_na_slot", retry_after=max_czekania) from None
        try:
            await tempo(klasa, max_tokens)
        except BaseException:
            sem.release()
            raise
    finally:
        st.przestan_czekac(tok)
    czekanie = time.perf_counter() - t0
    # TODO ćw. 01: czas czekania na slot (`czekanie`) jest teraz niewidoczny.
    #   1) span `llm.queue_wait` od t0_ns do teraz — RODZEŃSTWO spanu wywołania, nie rodzic:
    #      telemetry.tracer.start_span(..., start_time=t0_ns) + .end() (bez aktywowania kontekstu),
    #   2) atrybut `llm.queue.wait_ms` na spanie żądania (trace.get_current_span()),
    #   3) histogram telemetry.H_CZEKANIE z atrybutem klasa (telemetry.zapisz(...)).
    st.w_toku += 1
    try:
        yield czekanie
    finally:
        st.w_toku -= 1
        sem.release()


async def tempo(klasa: str, max_tokens: int) -> None:
    """TODO ćw. 08 (W4): poczekaj, aż limit dostawcy (żądania/min, tokeny wyjścia/min) pozwoli na wywołanie.

    Teraz nie ograniczamy niczego — przy ruchu powyżej limitu dostawca odpowiada 429.
    """
    return None


def aktualizuj_z_naglowkow(status: int, naglowki) -> None:
    """TODO ćw. 08: wołane z haka HTTP dla każdej odpowiedzi dostawcy `a`.

    Nagłówki: anthropic-ratelimit-{requests,output-tokens}-{limit,remaining,reset}, retry-after (przy 429).
    """
    return None
