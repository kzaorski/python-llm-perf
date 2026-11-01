"""Klasyfikacja zgłoszeń (typ sprawy) — endpoint POST /claims/{n}/classify.

Ćw. 04 (W1): handler `async def` woła SYNCHRONICZNY klient `anthropic.Anthropic`. Wywołanie blokuje
pętlę zdarzeń na cały czas odpowiedzi LLM: N równoległych klasyfikacji trwa ≈ N × t, a w tym czasie
stoi KAŻDY inny endpoint tego procesu (także /health). W trace widać luki, w metryce — lag pętli.
TODO ćw. 04: użyj ścieżki asynchronicznej (obsluga.wykonaj z Zadaniem klasy „krotkie").
"""
from __future__ import annotations

import time

import anthropic
from fastapi import APIRouter, Request

from . import config, dane, obsluga
from .llm import Zadanie  # noqa: F401 — przyda się w ćw. 04

router = APIRouter()

KATEGORIE = ("szkoda komunikacyjna", "szkoda majątkowa", "zdrowie i życie", "odpowiedzialność cywilna")
SYSTEM = "Jesteś asystentem likwidatora szkód. Odpowiadasz jedną kategorią z listy."

_klient_sync = anthropic.Anthropic(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)


def _prompt(n: int) -> str:
    return (f"Kategorie: {', '.join(KATEGORIE)}.\nSklasyfikuj zgłoszenie:\n"
            f"{dane.opis_dla_llm(dane.zgloszenie(n))}")


def _kategoria(tekst: str, n: int) -> str:
    # atrapa zwraca losowe słowa — kategorię wybieramy deterministycznie z odpowiedzi
    return KATEGORIE[(len(tekst) + n) % len(KATEGORIE)]


@router.post("/claims/{n}/classify")
async def klasyfikuj(n: int, request: Request):
    t0 = time.perf_counter()
    m = _klient_sync.messages.create(model=config.LLM_MODEL, max_tokens=16, system=SYSTEM,
                                     messages=[{"role": "user", "content": _prompt(n)}],
                                     extra_headers=obsluga.naglowki_atrapy(request) or None)   # W1: blokuje pętlę
    tekst = "".join(b.text for b in m.content if b.type == "text")
    obsluga.zapisz_wynik(request, "classify", "krotkie", "ok", t0, {"llm": time.perf_counter() - t0})
    return {"zgloszenie": dane.zgloszenie(n)["id"], "kategoria": _kategoria(tekst, n)}

