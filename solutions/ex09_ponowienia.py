"""[ROZWIĄZANIE ćw. 09 — kopiuj do app/llm/ponowienia.py] Ponowienia na poziomie aplikacji.

Ćw. 09 (W5) ✅ — jedna warstwa ponowień (SDK: max_retries=0, app/llm/klient.py):
- wykładniczy backoff z PEŁNYM jitterem: przerwa = U(0, min(limit, baza·2^próba)) — klienci, którzy
  dostali błąd w tej samej chwili, nie wracają razem tą samą falą;
- `retry-after` od dostawcy ma pierwszeństwo (429/529 mówią, kiedy wrócić);
- budżet ponowień: ponowienia ≤ 20% udanych/wszystkich żądań w ostatnim oknie — przy masowej awarii
  nie mnożymy ruchu do przeciążonego dostawcy (zamiast ×3 wychodzi ×1.2);
- NIE ponawiamy timeoutów: dostawca, który nie odpowiedział w czasie, zwykle nadal pracuje nad
  poprzednią próbą — powtórka podwaja jego obciążenie i nasz czas czekania (ćw. 10, W17).
"""
from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from collections.abc import Awaitable, Callable

import anthropic
import httpx2

PROBY = 3                  # 1 + 2 ponowienia
BAZA_S = 0.5
LIMIT_S = 8.0
BUDZET = 0.2               # ponowienia / żądania w oknie
OKNO_S = 10.0

_zadania: deque[float] = deque()
_ponowienia: deque[float] = deque()


def _przytnij(d: deque, teraz: float) -> None:
    while d and d[0] < teraz - OKNO_S:
        d.popleft()


def _budzet_pozwala() -> bool:
    teraz = time.monotonic()
    _przytnij(_zadania, teraz)
    _przytnij(_ponowienia, teraz)
    return len(_ponowienia) < max(1.0, BUDZET * len(_zadania))


def _do_ponowienia(e: Exception) -> bool:
    if isinstance(e, (anthropic.APITimeoutError, httpx2.TimeoutException)):
        return False                     # timeout ≠ chwilowy błąd (patrz docstring)
    return isinstance(e, (anthropic.RateLimitError, anthropic.OverloadedError, anthropic.InternalServerError,
                          anthropic.APIConnectionError))


def _przerwa(e: Exception, proba: int) -> float:
    resp = getattr(e, "response", None)
    ra = resp.headers.get("retry-after") if resp is not None else None
    if ra:
        try:
            return float(ra) + random.uniform(0, 0.5)
        except ValueError:
            pass
    return random.uniform(0, min(LIMIT_S, BAZA_S * 2 ** proba))


async def z_ponowieniami(fn: Callable[[], Awaitable]):
    _zadania.append(time.monotonic())
    for proba in range(1, PROBY + 1):
        try:
            return await fn()
        except Exception as e:
            if proba == PROBY or not _do_ponowienia(e) or not _budzet_pozwala():
                raise
            _ponowienia.append(time.monotonic())
            await asyncio.sleep(_przerwa(e, proba))
