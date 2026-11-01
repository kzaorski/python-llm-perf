"""[ROZWIĄZANIE ćw. 15 — kopiuj do app/cache.py] Odpowiedzi na częste pytania klientów (FAQ) z cache w Redisie — endpoint GET /faq?q=…

Ćw. 15 (W10): cache bez single-flight. Gdy klucz wygaśnie (albo jeszcze go nie ma), każde z N
równoczesnych identycznych pytań widzi „miss" i SAMO woła LLM — N wywołań zamiast jednego
(cache stampede). Przy popularnym pytaniu to fala ruchu do dostawcy co TTL sekund.
✅ ćw. 15: single-flight (w procesie Future, między procesami blokada SET NX w Redisie).
"""
from __future__ import annotations

import asyncio
import hashlib
import os

import redis.asyncio as aioredis
from fastapi import APIRouter, Request

from . import config, obsluga, telemetry
from .llm import Zadanie

router = APIRouter()
r = aioredis.from_url(config.REDIS_URL, decode_responses=True)
TTL_S = int(os.environ.get("FAQ_TTL_S", "60"))


def klucz(q: str) -> str:
    return "faq:" + hashlib.sha1(q.strip().lower().encode()).hexdigest()[:16]


async def policz(q: str, request: Request) -> str:
    z = Zadanie(klasa="krotkie", endpoint="faq", max_tokens=300,
                prompt=f"Odpowiedz klientowi ubezpieczyciela na pytanie: {q}",
                naglowki=obsluga.naglowki_atrapy(request))
    return (await obsluga.wykonaj(request, z)).tekst


_w_toku: dict[str, asyncio.Future] = {}
BLOKADA_S = 30            # blokada międzyprocesowa: dłużej niż deadline krótkich (30 s)


async def pobierz_albo_policz(k: str, q: str, request: Request) -> tuple[str, str]:
    """ćw. 15 (W10) ✅ single-flight: jedno wywołanie LLM na klucz, reszta czeka na jego wynik.

    1) w procesie: słownik klucz → Future (pierwszy liczy, pozostali `await` na tym samym Future);
    2) między procesami (np. kilka workerów gunicorna): blokada w Redisie `SET … NX PX` — kto nie
       zdobył blokady, czeka, aż wartość pojawi się w cache (odpytywanie co 50 ms).
    Zwraca (odpowiedź, skąd) — skąd: hit | miss | wspolne (czekał na cudze wywołanie).
    """
    v = await r.get(k)
    if v is not None:
        telemetry.zapisz(telemetry.C_CACHE, 1, wynik="hit")
        return v, "hit"
    if k in _w_toku:
        telemetry.zapisz(telemetry.C_CACHE, 1, wynik="wspolne")
        return await asyncio.shield(_w_toku[k]), "wspolne"
    fut = asyncio.get_running_loop().create_future()
    _w_toku[k] = fut
    try:
        if await r.set(k + ":blokada", "1", nx=True, px=BLOKADA_S * 1000):
            try:
                telemetry.zapisz(telemetry.C_CACHE, 1, wynik="miss")
                v = await policz(q, request)
                await r.set(k, v, ex=TTL_S)
                skad = "miss"
            finally:
                await r.delete(k + ":blokada")
        else:                                   # liczy inny proces — czekamy na wynik w cache
            telemetry.zapisz(telemetry.C_CACHE, 1, wynik="wspolne")
            skad = "wspolne"
            for _ in range(BLOKADA_S * 20):
                v = await r.get(k)
                if v is not None:
                    break
                await asyncio.sleep(0.05)
            else:
                v = await policz(q, request)    # właściciel blokady padł — liczymy sami
        fut.set_result(v)
        return v, skad
    except BaseException as e:
        if not fut.done():
            fut.set_exception(e)
            fut.exception()                     # oznacz jako odczytany (brak ostrzeżeń asyncio)
        raise
    finally:
        _w_toku.pop(k, None)


@router.get("/faq")
async def faq(q: str, request: Request):
    v, skad = await pobierz_albo_policz(klucz(q), q, request)
    return {"pytanie": q, "odpowiedz": v, "cache": skad}
