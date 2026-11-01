"""[ROZWIĄZANIE ćw. 08 (zawiera 01, 06) — kopiuj do app/llm/limiter.py] Sloty LLM: ile wywołań naraz (semafor) i w jakim tempie (limiter dostawcy).

Ćw. 01 — ✅ czas czekania na slot w trace (span llm.queue_wait, atrybut llm.queue.wait_ms) i w metrykach.
Ćw. 06 — ✅ rozmiar puli z prawa Little'a (W3: było 4).
Ćw. 08 — ✅ limiter tempa z nagłówków anthropic-ratelimit-* i retry-after (W4).
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

from opentelemetry import trace

from .. import stan, telemetry
from ..bledy import Odrzucone

# ćw. 06 (W3): rozmiar puli z prawa Little'a: L = λ · W.
#   Ruch docelowy λ ≈ 20 żądań/s, czas wywołania W ≈ 1.3 s (p50 streszczenia u atrapy; p99 ~1.8 s)
#   → średnio 26 wywołań w toku. Zapas na ogon i chwilowe skoki: 32. Więcej nie pomoże, gdy
#   ograniczeniem jest dostawca (moc/limity) — wtedy kolejka przenosi się do niego (ćw. 08, 12).
SLOTY = int(os.environ.get("LLM_SLOTY", "32"))
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
    # ćw. 01: czas czekania widoczny w trace i w metrykach.
    # Span czekania tworzymy BEZ aktywowania (start_span, nie start_as_current_span): jest rodzeństwem
    # spanu `llm.call`, a nie jego rodzicem — inaczej wywołanie wyglądałoby na część czekania.
    s = telemetry.tracer.start_span("llm.queue_wait", start_time=t0_ns,
                                    attributes={"app.klasa": klasa, "llm.waiting_przy_wejsciu": st.liczba_czekajacych})
    s.end()
    trace.get_current_span().set_attribute("llm.queue.wait_ms", round(czekanie * 1000, 1))
    telemetry.zapisz(telemetry.H_CZEKANIE, czekanie, klasa=klasa)
    st.w_toku += 1
    try:
        yield czekanie
    finally:
        st.w_toku -= 1
        sem.release()


class Kubelek:
    """Token bucket „po naszej stronie", zsynchronizowany z nagłówkami dostawcy.

    limit/min poznajemy z `anthropic-ratelimit-*-limit`, a poziom korygujemy w dół do `*-remaining`
    (dostawca wie lepiej, ile zostało — np. gdy ruch idzie też z innych procesów).
    """

    def __init__(self) -> None:
        self.limit: float | None = None      # na minutę; None = jeszcze nie znamy
        self.poziom = 0.0
        self.t = time.monotonic()

    def _uzupelnij(self) -> None:
        now = time.monotonic()
        if self.limit:
            self.poziom = min(self.limit, self.poziom + (now - self.t) * self.limit / 60.0)
        self.t = now

    def czas_do(self, n: float) -> float:
        if not self.limit:
            return 0.0
        self._uzupelnij()
        n = min(n, self.limit)
        return 0.0 if self.poziom >= n else (n - self.poziom) * 60.0 / self.limit

    def zabierz(self, n: float) -> None:
        if self.limit:
            self._uzupelnij()
            self.poziom -= n

    def synchronizuj(self, limit: int, pozostalo: int) -> None:
        self._uzupelnij()
        if self.limit != limit:
            self.limit = float(limit)
            self.poziom = float(pozostalo)
        else:
            self.poziom = min(self.poziom, float(pozostalo))


_ZADANIA = Kubelek()        # żądania / min (RPM)
_TOKENY_WYJ = Kubelek()     # tokeny wyjścia / min (OTPM) — dostawca rezerwuje max_tokens na starcie
_pauza_do = 0.0             # po 429: wszyscy czekają do retry-after
_kolejnosc = asyncio.Lock()  # FIFO: kto pierwszy czekał, ten pierwszy dostaje token
_sonda_wyslana = False
_poznano_limity = asyncio.Event()


async def tempo(klasa: str, max_tokens: int) -> None:
    """ćw. 08 (W4): czekaj, aż limity dostawcy pozwolą na wywołanie — zamiast zbierać 429.

    Przed pierwszą odpowiedzią limitów nie znamy: pierwsze żądanie idzie jako sonda nagłówków,
    reszta czeka na nie (max 10 s) — inaczej pierwsza fala ruchu i tak trafiłaby w 429.
    """
    global _sonda_wyslana
    if not _poznano_limity.is_set():
        if not _sonda_wyslana:
            _sonda_wyslana = True
            return
        try:
            await asyncio.wait_for(_poznano_limity.wait(), 10.0)
        except TimeoutError:
            _poznano_limity.set()       # dostawca nie podaje limitów — nie ograniczamy
    async with _kolejnosc:
        while True:
            czekaj = max(_pauza_do - time.monotonic(), _ZADANIA.czas_do(1), _TOKENY_WYJ.czas_do(max_tokens))
            if czekaj <= 0:
                _ZADANIA.zabierz(1)
                _TOKENY_WYJ.zabierz(max_tokens)
                return
            await asyncio.sleep(min(czekaj, 1.0))


def aktualizuj_z_naglowkow(status: int, naglowki) -> None:
    """ćw. 08: limity i pozostałe zasoby z nagłówków; 429 → wstrzymanie wszystkich do retry-after."""
    global _pauza_do
    for kubelek, nazwa in ((_ZADANIA, "requests"), (_TOKENY_WYJ, "output-tokens")):
        lim = naglowki.get(f"anthropic-ratelimit-{nazwa}-limit")
        poz = naglowki.get(f"anthropic-ratelimit-{nazwa}-remaining")
        if lim and poz:
            kubelek.synchronizuj(int(lim), int(poz))
            _poznano_limity.set()
    if status == 429:
        ra = naglowki.get("retry-after")
        _pauza_do = max(_pauza_do, time.monotonic() + (float(ra) if ra else 1.0))
