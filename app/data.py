"""Domain data: insurance claims from data/claims.jsonl (scripts/generate_claims.py).

A claim is addressed by a sequence number `n` (1…20000) — the numeric part of `CLM/2026/000123`.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

from . import config


@lru_cache(maxsize=1)
def _all_claims() -> list[dict]:
    if not os.path.exists(config.DATA_PATH):
        raise RuntimeError(f"Missing {config.DATA_PATH} — run: python scripts/generate_claims.py")
    with open(config.DATA_PATH, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def count() -> int:
    return len(_all_claims())


def claim(n: int) -> dict:
    zs = _all_claims()
    return zs[(n - 1) % len(zs)]


def describe_for_llm(z: dict) -> str:
    return (f"Claim {z['id']} ({z['type']}), policy {z['policy']}, customer {z['customer']}, "
            f"city {z['city']}, channel {z['channel']}, incident date {z['incident_date']}, "
            f"estimated amount {z['estimated_amount_usd']} USD.\nDescription: {z['description']}")
