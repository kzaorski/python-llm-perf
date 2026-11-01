"""[ROZWIĄZANIE ćw. 11 — kopiuj do app/llm/fallback.py] Zapasowy dostawca z wyłącznikiem (circuit breaker).

Ćw. 11 (W12) ✅ — stany wyłącznika dostawcy `a`:
- ZAMKNIĘTY: ruch idzie do `a`; liczymy kolejne awarie;
- OTWARTY: po PROG_AWARII kolejnych awariach przez CZAS_OTWARCIA_S nie pytamy `a` wcale — od razu `b`
  (żądanie nie płaci timeoutu `a`, a `a` dostaje czas na podniesienie się);
- PÓŁOTWARTY: po czasie otwarcia JEDNO żądanie-próbka idzie do `a`; sukces zamyka wyłącznik,
  porażka otwiera go ponownie.
Stan wyłącznika: atrybut `llm.cb.stan` na spanie `llm.call` i w /diag (licznik zmian stanu).
"""
from __future__ import annotations

import os
import time

import anthropic
from opentelemetry import trace

from .. import config, stan
from . import Wynik, Zadanie, klient

BLEDY_AWARII = (anthropic.APIConnectionError, anthropic.InternalServerError)
PROG_AWARII = int(os.environ.get("CB_PROG", "5"))
CZAS_OTWARCIA_S = float(os.environ.get("CB_OTWARCIE_S", "30"))


def _awaria(e: Exception) -> bool:
    if isinstance(e, anthropic.OverloadedError):
        return False   # 529 overloaded = przeciążenie, nie awaria — fallback przeniósłby burzę na `b`
    return isinstance(e, BLEDY_AWARII)


class Wylacznik:
    def __init__(self) -> None:
        self.stan = "zamkniety"
        self.awarie = 0
        self.otwarty_do = 0.0
        self.probka_w_toku = False

    def _ustaw(self, nowy: str) -> None:
        if nowy != self.stan:
            stan.WYNIKI[("cb", "a", f"{self.stan}->{nowy}")] += 1
            self.stan = nowy

    def czy_pytac_a(self) -> bool:
        if self.stan == "zamkniety":
            return True
        if self.stan == "otwarty" and time.monotonic() >= self.otwarty_do:
            self._ustaw("polotwarty")
        if self.stan == "polotwarty" and not self.probka_w_toku:
            self.probka_w_toku = True
            return True
        return False

    def sukces(self) -> None:
        self.awarie = 0
        self.probka_w_toku = False
        self._ustaw("zamkniety")

    def awaria(self) -> None:
        self.awarie += 1
        self.probka_w_toku = False
        if self.stan == "polotwarty" or self.awarie >= PROG_AWARII:
            self.otwarty_do = time.monotonic() + CZAS_OTWARCIA_S
            self._ustaw("otwarty")


WYLACZNIK = Wylacznik()


async def wywolaj(z: Zadanie) -> Wynik:
    trace.get_current_span().set_attribute("llm.cb.stan", WYLACZNIK.stan)
    if not config.LLM_FALLBACK:
        return await klient.zapytaj(z, "a")
    if WYLACZNIK.czy_pytac_a():
        try:
            w = await klient.zapytaj(z, "a")
            WYLACZNIK.sukces()
            return w
        except Exception as e:
            if not _awaria(e):
                WYLACZNIK.probka_w_toku = False
                raise
            WYLACZNIK.awaria()
    return await klient.zapytaj(z, "b")
