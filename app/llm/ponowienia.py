"""Ponowienia na poziomie aplikacji.

Ćw. 09 (W5): ponawiamy szybko (stałe 100 ms, bez backoffu i jittera) do 3 prób — NAD ponowieniami SDK
(`max_retries=2` w app/llm/klient.py). Przy przeciążonym dostawcy jedna prośba użytkownika zamienia się
w do 3×3 = 9 prób HTTP, wysyłanych falami w tym samym rytmie przez wszystkich klientów naraz.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import anthropic

PROBY = 3
PRZERWA_S = 0.1


async def z_ponowieniami(fn: Callable[[], Awaitable]):
    for proba in range(1, PROBY + 1):
        try:
            return await fn()
        except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError):
            # InternalServerError obejmuje 5xx i 529 overloaded; APIConnectionError — także timeouty
            if proba == PROBY:
                raise
            await asyncio.sleep(PRZERWA_S)
