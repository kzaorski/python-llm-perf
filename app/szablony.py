"""Pisma do klientów z szablonów — endpoint POST /claims/{n}/letter.

Moduł „szablonów" jest synchroniczny (renderowanie + synchroniczny klient LLM), więc handler jest
zwykłym `def`. FastAPI uruchamia takie handlery w puli wątków anyio, której limit to 40 wątków.

Ćw. 05 (W2): przy > 40 równoległych żądaniach nadmiar czeka na wolny wątek — bez zużycia CPU,
bez śladu w kodzie aplikacji; czas odpowiedzi rośnie schodkami co ~40 żądań.
TODO ćw. 05: handler `async def` + asynchroniczny klient (app/llm/klient.py: `klient.zapytaj`).
"""
from __future__ import annotations

import time
from string import Template

import anthropic
from fastapi import APIRouter, Request

from . import config, dane, obsluga

router = APIRouter()

SZABLON = Template("Szanowna Pani / Szanowny Panie $klient,\n\nw sprawie zgłoszenia $id (polisa $polisa) "
                   "informujemy:\n$tresc\n\nZ poważaniem\nDział Likwidacji Szkód")

_klient_sync = anthropic.Anthropic(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)


def _prompt(z: dict) -> str:
    return f"Napisz krótką, uprzejmą informację o dalszych krokach likwidacji.\n{dane.opis_dla_llm(z)}"


def renderuj(z: dict, tresc: str) -> str:
    return SZABLON.substitute(klient=z["klient"], id=z["id"], polisa=z["polisa"], tresc=tresc.strip())


@router.post("/claims/{n}/letter")
def pismo(n: int, request: Request):   # W2: `def` → pula wątków anyio (40)
    t0 = time.perf_counter()
    z = dane.zgloszenie(n)
    m = _klient_sync.messages.create(model=config.LLM_MODEL, max_tokens=300,
                                     messages=[{"role": "user", "content": _prompt(z)}],
                                     extra_headers=obsluga.naglowki_atrapy(request) or None)
    tekst = "".join(b.text for b in m.content if b.type == "text")
    obsluga.zapisz_wynik(request, "letter", "krotkie", "ok", t0, {"llm": time.perf_counter() - t0})
    return {"zgloszenie": z["id"], "pismo": renderuj(z, tekst)}
