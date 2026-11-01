"""[ROZWIĄZANIE ćw. 12 — kopiuj do app/przeciazenie.py] Backpressure i odrzucanie nadmiaru.

Ćw. 12 ✅ (W7, W8):
- W7: limit kolejki per klasa — gdy czeka już MAX_CZEKAJACYCH, nowe żądanie dostaje od razu 503
  + Retry-After (milisekundy zamiast minut; klient może ponowić później albo pójść gdzie indziej);
- W8: budżet czekania per klasa — kto nie dostał slotu w MAX_CZEKANIA_S, dostaje 503 zamiast czekać
  dalej (jego klient i tak by już zrezygnował; praca po terminie to praca zmarnowana).
Wartości z Little'a: kolejka krótkich ≈ przepustowość × akceptowalne czekanie
(32 sloty / ~1.6 s ≈ 20/s × 2 s ≈ 40 → 64 z zapasem); długie: 8 w kolejce, max 20 s czekania.
"""
from __future__ import annotations

import os

from . import stan
from .bledy import Odrzucone

MAX_CZEKAJACYCH = {"krotkie": int(os.environ.get("KOLEJKA_KROTKIE", "64")),
                   "dlugie": int(os.environ.get("KOLEJKA_DLUGIE", "8"))}
MAX_CZEKANIA_S = {"krotkie": float(os.environ.get("CZEKANIE_KROTKIE_S", "5")),
                  "dlugie": float(os.environ.get("CZEKANIE_DLUGIE_S", "20"))}


def dopusc(klasa: str) -> None:
    if stan.STAN[klasa].liczba_czekajacych >= MAX_CZEKAJACYCH[klasa]:
        raise Odrzucone("kolejka_pelna", retry_after=MAX_CZEKANIA_S[klasa])


def max_czekania(klasa: str) -> float | None:
    return MAX_CZEKANIA_S[klasa]
