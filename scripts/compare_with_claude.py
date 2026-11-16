#!/usr/bin/env python3
"""Ex. 17 — mock vs real Claude: the distribution of TTFT, total time, token rate and the limit headers.

    export ANTHROPIC_API_KEY=...             # in this shell only; do not save it in the repo
    python scripts/compare_with_claude.py    # 8 × 3 tasks on each provider, Claude cost ≈ $0.005
    python scripts/compare_with_claude.py --mock-only

Output: results/ex17-comparison.json ("mock" and "claude" sections) + a table on the console.
Sequential calls, streaming, `thinking` disabled. Model: LLM_MODEL (default claude-haiku-5-5).
Pricing for the cost estimate: PRICE_IN / PRICE_OUT [$ per 1 million tokens] (default 0.10 / 0.50 — check the current prices).
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
from app import data  # noqa: E402

MODEL = os.environ.get("LLM_MODEL", "claude-haiku-5-5")
PRICE_IN = float(os.environ.get("PRICE_IN", "0.10"))
PRICE_OUT = float(os.environ.get("PRICE_OUT", "0.50"))
TASKS = {"classification": 16, "summary": 200, "reply": 700}


def measure(k: anthropic.Anthropic, n: int) -> dict:
    out: dict = {"tasks": {}, "headers": {}}
    tok_in = tok_out = 0
    ttft_all, total_all = [], []
    for name, max_tokens in TASKS.items():
        rows = []
        for i in range(n):
            z = data.claim(100 + i)
            t0 = time.perf_counter()
            ttft = None
            with k.messages.stream(
                    model=MODEL, max_tokens=max_tokens, thinking={"type": "disabled"},
                    messages=[{"role": "user", "content": f"{name} of the claim:\n{data.describe_for_llm(z)}"}]) as s:
                if not out["headers"] and getattr(s, "response", None) is not None:
                    out["headers"] = {h: v for h, v in s.response.headers.items() if h.startswith("anthropic-ratelimit")}
                for _ in s.text_stream:
                    if ttft is None:
                        ttft = time.perf_counter() - t0
                m = s.get_final_message()
            total = time.perf_counter() - t0
            tok_in += m.usage.input_tokens
            tok_out += m.usage.output_tokens
            rows.append({"ttft_s": ttft, "total_s": total, "tok_out": m.usage.output_tokens})
            ttft_all.append(ttft or total)
            total_all.append(total)
        tps = [w["tok_out"] / max(1e-3, w["total_s"] - (w["ttft_s"] or 0)) for w in rows if w["tok_out"] > 20]
        out["tasks"][name] = {
            "ttft_p50_s": round(statistics.median(w["ttft_s"] or w["total_s"] for w in rows), 3),
            "ttft_max_s": round(max(w["ttft_s"] or w["total_s"] for w in rows), 3),
            "total_p50_s": round(statistics.median(w["total_s"] for w in rows), 3),
            "tok_per_s_p50": round(statistics.median(tps), 1) if tps else None}
    out["ttft_p50_s"] = round(statistics.median(ttft_all), 3)
    out["cost_usd"] = round(tok_in / 1e6 * PRICE_IN + tok_out / 1e6 * PRICE_OUT, 5)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=8)
    ap.add_argument("--mock-only", action="store_true")
    a = ap.parse_args()
    result = {"model": MODEL, "n": a.n, "time": time.strftime("%Y-%m-%dT%H:%M:%S")}
    mock = anthropic.Anthropic(base_url=os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8061"),
                               api_key=os.environ.get("LLM_API_KEY", "mock-key"), max_retries=0)
    result["mock"] = measure(mock, a.n)
    if not a.mock_only:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit("Missing ANTHROPIC_API_KEY (or use --mock-only).")
        claude = anthropic.Anthropic(base_url="https://api.anthropic.com", max_retries=2)
        result["claude"] = measure(claude, a.n)
    os.makedirs(os.path.join(REPO, "results"), exist_ok=True)
    with open(os.path.join(REPO, "results", "ex17-comparison.json"), "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    for src in ("mock", "claude"):
        if src in result:
            print(f"\n{src}: TTFT p50 {result[src]['ttft_p50_s']} s, cost ${result[src]['cost_usd']}")
            for z, v in result[src]["tasks"].items():
                print(f"  {z:14s} {v}")


if __name__ == "__main__":
    main()
