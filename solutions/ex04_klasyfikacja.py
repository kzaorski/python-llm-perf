"""[ROZWIĄZANIE ćw. 04 — kopiuj do app/klasyfikacja.py] Klasyfikacja zgłoszeń (typ sprawy) — endpoint POST /claims/{n}/classify.

Ćw. 04 (W1): handler `async def` woła SYNCHRONICZNY klient `anthropic.Anthropic`. Wywołanie blokuje
pętlę zdarzeń na cały czas odpowiedzi LLM: N równoległych klasyfikacji trwa ≈ N × t, a w tym czasie
stoi KAŻDY inny endpoint tego procesu (także /health). W trace widać luki, w metryce — lag pętli.
✅ ćw. 04: ścieżka asynchroniczna (obsluga.wykonaj).
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from . import dane, obsluga
from .llm import Zadanie

router = APIRouter()

KATEGORIE = ("szkoda komunikacyjna", "szkoda majątkowa", "zdrowie i życie", "odpowiedzialność cywilna")
SYSTEM = "Jesteś asystentem likwidatora szkód. Odpowiadasz jedną kategorią z listy."


def _prompt(n: int) -> str:
    return (f"Kategorie: {', '.join(KATEGORIE)}.\nSklasyfikuj zgłoszenie:\n"
            f"{dane.opis_dla_llm(dane.zgloszenie(n))}")


def _kategoria(tekst: str, n: int) -> str:
    # atrapa zwraca losowe słowa — kategorię wybieramy deterministycznie z odpowiedzi
    return KATEGORIE[(len(tekst) + n) % len(KATEGORIE)]


@router.post("/claims/{n}/classify")
async def klasyfikuj(n: int, request: Request):
    # ćw. 04 (W1) ✅: asynchroniczna ścieżka (AsyncAnthropic przez obsluga.wykonaj) — `await` oddaje
    # pętlę zdarzeń innym żądaniom na czas czekania na LLM; dochodzi slot, limity, deadline itd.
    w = await obsluga.wykonaj(request, Zadanie(klasa="krotkie", endpoint="classify", max_tokens=16,
                                               system=SYSTEM, prompt=_prompt(n),
                                               naglowki=obsluga.naglowki_atrapy(request)))
    return {"zgloszenie": dane.zgloszenie(n)["id"], "kategoria": _kategoria(w.tekst, n)}
