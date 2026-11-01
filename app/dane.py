"""Dane domenowe: zgłoszenia szkodowe z data/zgloszenia.jsonl (scripts/generuj_zgloszenia.py).

Zgłoszenie wskazujemy numerem porządkowym `n` (1…20000) — część numeryczna `SZK/2026/000123`.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

from . import config


@lru_cache(maxsize=1)
def _wszystkie() -> list[dict]:
    if not os.path.exists(config.DATA_PATH):
        raise RuntimeError(f"Brak {config.DATA_PATH} — uruchom: python scripts/generuj_zgloszenia.py")
    with open(config.DATA_PATH, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def liczba() -> int:
    return len(_wszystkie())


def zgloszenie(n: int) -> dict:
    zs = _wszystkie()
    return zs[(n - 1) % len(zs)]


def opis_dla_llm(z: dict) -> str:
    return (f"Zgłoszenie {z['id']} ({z['typ']}), polisa {z['polisa']}, klient {z['klient']}, "
            f"miasto {z['miasto']}, kanał {z['kanal']}, data zdarzenia {z['data_zdarzenia']}, "
            f"kwota szacowana {z['kwota_szacowana_pln']} PLN.\nOpis: {z['opis']}")
