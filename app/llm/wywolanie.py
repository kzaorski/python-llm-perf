"""Wywołanie LLM z deadline'em całkowitym i anulowaniem po rozłączeniu klienta.

Ćw. 10 — TODO (W6, W16): teraz wywołanie trwa tak długo, jak chce dostawca:
- brak deadline'u całkowitego: `timeout` SDK to limit PER OPERACJA (read = bezczynność), więc strumień
  albo zawieszony dostawca może trzymać slot minutami;
- brak anulowania: gdy klient (k6, przeglądarka, proxy) się rozłączy, aplikacja dalej czeka na LLM,
  trzyma slot semafora, a dostawca generuje (i liczy) tokeny, których nikt nie odbierze.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request


async def z_deadlinem(request: Request | None, klasa: str, fn: Callable[[], Awaitable]):
    """TODO ćw. 10: deadline per klasa (asyncio.timeout) + przerwanie, gdy klient się rozłączy.

    Po przekroczeniu deadline'u rzuć bledy.Przeterminowane, po rozłączeniu — bledy.Anulowane.
    `request` może być None (wywołanie spoza HTTP, np. worker kolejki).
    """
    return await fn()
