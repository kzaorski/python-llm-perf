"""[ROZWIĄZANIE ćw. 05 — kopiuj do app/szablony.py] Pisma do klientów z szablonów — endpoint POST /claims/{n}/letter.

Moduł „szablonów" jest synchroniczny (renderowanie + synchroniczny klient LLM), więc handler jest
zwykłym `def`. FastAPI uruchamia takie handlery w puli wątków anyio, której limit to 40 wątków.

Ćw. 05 (W2): przy > 40 równoległych żądaniach nadmiar czeka na wolny wątek — bez zużycia CPU,
bez śladu w kodzie aplikacji; czas odpowiedzi rośnie schodkami co ~40 żądań.
✅ ćw. 05: `async def` + klient.zapytaj (AsyncAnthropic).
"""
from __future__ import annotations

import time
from string import Template

from fastapi import APIRouter, Request

from . import dane, obsluga
from .llm import Zadanie, klient

router = APIRouter()

SZABLON = Template("Szanowna Pani / Szanowny Panie $klient,\n\nw sprawie zgłoszenia $id (polisa $polisa) "
                   "informujemy:\n$tresc\n\nZ poważaniem\nDział Likwidacji Szkód")


def _prompt(z: dict) -> str:
    return f"Napisz krótką, uprzejmą informację o dalszych krokach likwidacji.\n{dane.opis_dla_llm(z)}"


def renderuj(z: dict, tresc: str) -> str:
    return SZABLON.substitute(klient=z["klient"], id=z["id"], polisa=z["polisa"], tresc=tresc.strip())


@router.post("/claims/{n}/letter")
async def pismo(n: int, request: Request):
    # ćw. 05 (W2) ✅: `async def` + AsyncAnthropic — żądanie nie zajmuje wątku z puli anyio (40)
    # na czas czekania na LLM. Renderowanie szablonu jest szybkie (µs CPU), więc może zostać w pętli.
    t0 = time.perf_counter()
    z = dane.zgloszenie(n)
    w = await klient.zapytaj(Zadanie(klasa="krotkie", endpoint="letter", max_tokens=300, prompt=_prompt(z),
                                     naglowki=obsluga.naglowki_atrapy(request)))
    obsluga.zapisz_wynik(request, "letter", "krotkie", "ok", t0, {"llm": w.czas_s})
    return {"zgloszenie": z["id"], "pismo": renderuj(z, w.tekst)}
