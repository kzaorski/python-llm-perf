"""Warstwa LLM: klient, limiter, deadline, ponowienia, fallback (tematy ćwiczeń 01, 06, 08–12)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Zadanie:
    """Jedno zlecenie dla LLM (niezależne od dostawcy)."""
    klasa: str                      # "krotkie" | "dlugie"
    endpoint: str
    prompt: str
    max_tokens: int
    system: str | None = None
    naglowki: dict = field(default_factory=dict)   # x-mock-* przekazywane atrapie


@dataclass
class Wynik:
    tekst: str
    tokeny_wej: int
    tokeny_wyj: int
    dostawca: str
    czas_s: float
    ttft_s: float | None = None
