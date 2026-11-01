"""Dopuszczanie żądań: backpressure i odrzucanie nadmiaru (load shedding).

Ćw. 12 — TODO (W7, W8):
- W7: kolejka do LLM bez limitu — każde żądanie staje w kolejce, nawet gdy przed nim czeka 500 innych;
  wiek najstarszego rośnie bez końca, a odpowiedzi przychodzą po minutach (albo już nikt na nie nie czeka);
- W8: brak budżetu czekania — nie ma szybkiego 503 dla części ruchu; wszyscy czekają długo.

app/obsluga.py woła:  przeciazenie.dopusc(klasa)  i  limiter.slot(..., max_czekania=przeciazenie.max_czekania(klasa))
"""
from __future__ import annotations


def dopusc(klasa: str) -> None:
    """TODO ćw. 12 (W7): rzuć bledy.Odrzucone, gdy w kolejce klasy czeka już za dużo żądań (stan.STAN)."""
    return None


def max_czekania(klasa: str) -> float | None:
    """TODO ćw. 12 (W8): ile sekund żądanie klasy może czekać na slot, zanim dostanie 503 (None = bez limitu)."""
    return None
