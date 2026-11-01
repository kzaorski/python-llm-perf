"""Zapasowy dostawca (fallback) a → b.

Ćw. 11 (W12): przy awarii `a` KAŻDE żądanie najpierw płaci pełny koszt porażki u `a` (np. timeout),
a dopiero potem idzie do `b`. Brak wyłącznika (circuit breaker): nie pamiętamy, że `a` leży.
TODO ćw. 11: wyłącznik — stany zamknięty → otwarty (po N porażkach) → półotwarty (próbka po czasie).
"""
from __future__ import annotations

import anthropic

from .. import config
from . import Wynik, Zadanie, klient

# Błędy, po których warto spróbować innego dostawcy: awaria/zawieszenie, nie „za dużo ruchu".
BLEDY_AWARII = (anthropic.APIConnectionError, anthropic.InternalServerError)


def _awaria(e: Exception) -> bool:
    if isinstance(e, anthropic.InternalServerError) and getattr(e, "status_code", 0) == 529:
        return False   # 529 overloaded = przeciążenie, nie awaria — fallback przeniósłby burzę na `b`
    return isinstance(e, BLEDY_AWARII)


async def wywolaj(z: Zadanie) -> Wynik:
    try:
        return await klient.zapytaj(z, "a")
    except Exception as e:
        if not (config.LLM_FALLBACK and _awaria(e)):
            raise
    return await klient.zapytaj(z, "b")
