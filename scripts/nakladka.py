#!/usr/bin/env python3
"""Nakładka rozwiązań: kopia aplikacji ze stanem „po ćwiczeniu NN" — bez ruszania Twojego app/.

    python scripts/nakladka.py --do 12                 # app/ + solutions/exKK_* (KK ≤ 12) → .run/do-12/
    python scripts/nakladka.py --do 18 --wady W3,W10   # stan końcowy z przywróconymi wadami (incydent)
    python scripts/nakladka.py --do 12 --cel .run/x    # własny katalog docelowy

Uruchomienie kopii (np. na porcie 8060, gdy Twoja aplikacja jest zatrzymana):
    uvicorn --app-dir .run/do-12 app.main:app --port 8060

Dla każdego modułu bierzemy NAJNOWSZE rozwiązanie kumulatywne z numerem ≤ NN (np. limiter: ex01 → ex06 →
ex08 → ex12). `--wady` cofa wskazane moduły do wersji sprzed ćwiczenia, które usuwa daną wadę.
Używają tego: smoke.sh (regresja `check.py --all` na rozwiązaniach) i incydent.sh (finał).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# moduł rozwiązania → plik w aplikacji
MODULY = {
    "limiter": "app/llm/limiter.py", "klient": "app/llm/klient.py", "wywolanie": "app/llm/wywolanie.py",
    "ponowienia": "app/llm/ponowienia.py", "fallback": "app/llm/fallback.py",
    "przeciazenie": "app/przeciazenie.py", "klasyfikacja": "app/klasyfikacja.py", "szablony": "app/szablony.py",
    "strumien": "app/strumien.py", "zadania": "app/zadania.py", "kolejka_metryki": "app/kolejka_metryki.py",
    "cache": "app/cache.py", "wsad": "app/wsad.py", "gunicorn": "gunicorn.conf.py",
}
# wada → (moduł, ćwiczenie, które ją usuwa)
WADY = {
    "W1": ("klasyfikacja", 4), "W2": ("szablony", 5), "W3": ("limiter", 6), "W4": ("limiter", 8),
    "W5": ("ponowienia", 9), "W6": ("klient", 10), "W7": ("przeciazenie", 12), "W8": ("przeciazenie", 12),
    "W9": ("strumien", 13), "W10": ("cache", 15), "W11": ("wsad", 16), "W12": ("fallback", 11),
    "W13": ("gunicorn", 7), "W15": ("zadania", 14), "W16": ("wywolanie", 10), "W17": ("klient", 10),
    "W18": ("limiter", 12),
}
# wady, których naprawa zmienia więcej niż jeden moduł: dodatkowe moduły cofane razem z główną
# (W5: ćw. 09 zmienia też klient.py — `max_retries=0`; bez tego cofnięta W5 nie mnoży prób przez SDK)
WADY_DODATKOWE = {"W5": [("klient", 9)]}
_WZOR = re.compile(r"^ex(\d\d)_(\w+?)\.(py)$")


def rozwiazania() -> dict[str, list[tuple[int, str]]]:
    out: dict[str, list[tuple[int, str]]] = {}
    for f in sorted(os.listdir(os.path.join(REPO, "solutions"))):
        m = _WZOR.match(f)
        if m and m.group(2) in MODULY:
            out.setdefault(m.group(2), []).append((int(m.group(1)), f))
    return out


def plan(do: int, wady: list[str]) -> dict[str, str | None]:
    """moduł → plik rozwiązania (None = zostaje wersja z app/, czyli szkielet)."""
    roz = rozwiazania()
    limit = {m: do for m in MODULY}
    for w in wady:
        for mod, cw in [WADY[w], *WADY_DODATKOWE.get(w, [])]:
            limit[mod] = min(limit[mod], cw - 1)
    out = {}
    for mod in MODULY:
        kandydaci = [f for n, f in roz.get(mod, []) if n <= limit[mod]]
        out[mod] = kandydaci[-1] if kandydaci else None
    return out


def zbuduj(do: int, wady: list[str], cel: str) -> dict:
    cel = os.path.abspath(cel)
    if os.path.exists(cel):
        shutil.rmtree(cel)
    os.makedirs(cel)
    shutil.copytree(os.path.join(REPO, "app"), os.path.join(cel, "app"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(os.path.join(REPO, "gunicorn.conf.py"), os.path.join(cel, "gunicorn.conf.py"))
    os.symlink(os.path.join(REPO, "data"), os.path.join(cel, "data"))
    p = plan(do, wady)
    for mod, plik in p.items():
        if plik:
            shutil.copy(os.path.join(REPO, "solutions", plik), os.path.join(cel, MODULY[mod]))
    return p


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--do", type=int, required=True, help="stan po ćwiczeniu NN (1–18)")
    ap.add_argument("--wady", default="", help="np. W3,W10 — przywróć te wady w stanie --do")
    ap.add_argument("--cel", default=None, help="katalog docelowy (domyślnie .run/do-NN)")
    a = ap.parse_args()
    wady = [w.strip().upper() for w in a.wady.split(",") if w.strip()]
    nieznane = [w for w in wady if w not in WADY]
    if nieznane:
        sys.exit(f"nieznane wady: {nieznane}; znane: {sorted(WADY)}")
    cel = a.cel or os.path.join(REPO, ".run", f"do-{a.do:02d}" + ("-" + "-".join(wady) if wady else ""))
    p = zbuduj(a.do, wady, cel)
    for mod, plik in p.items():
        print(f"  {MODULY[mod]:24s} ← {plik or '(szkielet z app/)'}")
    print(cel)


if __name__ == "__main__":
    main()
