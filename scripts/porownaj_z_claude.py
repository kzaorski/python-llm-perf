#!/usr/bin/env python3
"""Ćw. 17 — atrapa vs prawdziwy Claude: rozkład TTFT, czasu całkowitego, tempa tokenów i nagłówki limitów.

    export ANTHROPIC_API_KEY=...            # tylko w tej powłoce; nie zapisuj w repo
    python scripts/porownaj_z_claude.py      # 8 × 3 zadania na każdym dostawcy, koszt Claude ≈ $0.005
    python scripts/porownaj_z_claude.py --tylko-atrapa

Wynik: wyniki/ex17-porownanie.json (sekcje "atrapa" i "claude") + tabela na konsoli.
Wywołania sekwencyjne, strumieniem, `thinking` wyłączone. Model: LLM_MODEL (domyślnie claude-haiku-5-5).
Cennik do szacunku kosztu: CENA_WEJ / CENA_WYJ [$ za 1 mln tokenów] (domyślnie 0.10 / 0.50 — sprawdź aktualny).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

import anthropic

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from app import dane  # noqa: E402

MODEL = os.environ.get("LLM_MODEL", "claude-haiku-5-5")
CENA_WEJ = float(os.environ.get("CENA_WEJ", "0.10"))
CENA_WYJ = float(os.environ.get("CENA_WYJ", "0.50"))
ZADANIA = {"klasyfikacja": 16, "streszczenie": 200, "odpowiedz": 700}


def mierz(k: anthropic.Anthropic, n: int) -> dict:
    out: dict = {"zadania": {}, "naglowki": {}}
    tok_we = tok_wy = 0
    ttft_all, calosc_all = [], []
    for nazwa, max_tokens in ZADANIA.items():
        wiersze = []
        for i in range(n):
            z = dane.zgloszenie(100 + i)
            t0 = time.perf_counter()
            ttft = None
            with k.messages.stream(
                    model=MODEL, max_tokens=max_tokens, thinking={"type": "disabled"},
                    messages=[{"role": "user", "content": f"{nazwa} zgłoszenia:\n{dane.opis_dla_llm(z)}"}]) as s:
                if not out["naglowki"] and getattr(s, "response", None) is not None:
                    out["naglowki"] = {h: v for h, v in s.response.headers.items() if h.startswith("anthropic-ratelimit")}
                for _ in s.text_stream:
                    if ttft is None:
                        ttft = time.perf_counter() - t0
                m = s.get_final_message()
            cal = time.perf_counter() - t0
            tok_we += m.usage.input_tokens
            tok_wy += m.usage.output_tokens
            wiersze.append({"ttft_s": ttft, "calosc_s": cal, "tok_wy": m.usage.output_tokens})
            ttft_all.append(ttft or cal)
            calosc_all.append(cal)
        tps = [w["tok_wy"] / max(1e-3, w["calosc_s"] - (w["ttft_s"] or 0)) for w in wiersze if w["tok_wy"] > 20]
        out["zadania"][nazwa] = {
            "ttft_p50_s": round(statistics.median(w["ttft_s"] or w["calosc_s"] for w in wiersze), 3),
            "ttft_max_s": round(max(w["ttft_s"] or w["calosc_s"] for w in wiersze), 3),
            "calosc_p50_s": round(statistics.median(w["calosc_s"] for w in wiersze), 3),
            "tok_na_s_p50": round(statistics.median(tps), 1) if tps else None}
    out["ttft_p50_s"] = round(statistics.median(ttft_all), 3)
    out["koszt_usd"] = round(tok_we / 1e6 * CENA_WEJ + tok_wy / 1e6 * CENA_WYJ, 5)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=8)
    ap.add_argument("--tylko-atrapa", action="store_true")
    a = ap.parse_args()
    wynik = {"model": MODEL, "n": a.n, "czas": time.strftime("%Y-%m-%dT%H:%M:%S")}
    atrapa = anthropic.Anthropic(base_url=os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8061"),
                                 api_key=os.environ.get("LLM_API_KEY", "mock-key"), max_retries=0)
    wynik["atrapa"] = mierz(atrapa, a.n)
    if not a.tylko_atrapa:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit("Brak ANTHROPIC_API_KEY (albo użyj --tylko-atrapa).")
        claude = anthropic.Anthropic(base_url="https://api.anthropic.com", max_retries=2)
        wynik["claude"] = mierz(claude, a.n)
    os.makedirs(os.path.join(REPO, "wyniki"), exist_ok=True)
    with open(os.path.join(REPO, "wyniki", "ex17-porownanie.json"), "w") as f:
        json.dump(wynik, f, ensure_ascii=False, indent=1)
    for src in ("atrapa", "claude"):
        if src in wynik:
            print(f"\n{src}: TTFT p50 {wynik[src]['ttft_p50_s']} s, koszt ${wynik[src]['koszt_usd']}")
            for z, v in wynik[src]["zadania"].items():
                print(f"  {z:13s} {v}")


if __name__ == "__main__":
    main()
