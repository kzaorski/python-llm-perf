"""Odpowiedzi na częste pytania klientów (FAQ) z cache w Redisie — endpoint GET /faq?q=…

Ćw. 15 (W10): cache bez single-flight. Gdy klucz wygaśnie (albo jeszcze go nie ma), każde z N
równoczesnych identycznych pytań widzi „miss" i SAMO woła LLM — N wywołań zamiast jednego
(cache stampede). Przy popularnym pytaniu to fala ruchu do dostawcy co TTL sekund.
TODO ćw. 15: single-flight — tylko jedno wywołanie na klucz; pozostali czekają na jego wynik.
"""
from __future__ import annotations

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


async def pobierz_albo_policz(k: str, q: str, request: Request) -> tuple[str, str]:
    """Zwraca (odpowiedź, skąd) — skąd: hit | miss."""
    v = await r.get(k)
    if v is not None:
        telemetry.zapisz(telemetry.C_CACHE, 1, wynik="hit")
        return v, "hit"
    telemetry.zapisz(telemetry.C_CACHE, 1, wynik="miss")
    v = await policz(q, request)          # W10: każdy „miss" woła LLM osobno
    await r.set(k, v, ex=TTL_S)
    return v, "miss"


@router.get("/faq")
async def faq(q: str, request: Request):
    v, skad = await pobierz_albo_policz(klucz(q), q, request)
    return {"pytanie": q, "odpowiedz": v, "cache": skad}
