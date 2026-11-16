"""Claim classification (type of case) — endpoint POST /claims/{n}/classify.

Ex. 04 (F1): the `async def` handler calls the SYNCHRONOUS `anthropic.Anthropic` client. The call blocks
the event loop for the whole LLM response time: N parallel classifications take ≈ N × t, and during that time
EVERY other endpoint of this process stands still (including /health). The trace shows gaps, the loop lag metric shows it.
TODO ex. 04: use the asynchronous path (pipeline.execute with an LLMJob of class "short").
"""
from __future__ import annotations

import time

import anthropic
from fastapi import APIRouter, Request

from . import config, data, pipeline
from .llm import LLMJob  # noqa: F401 — you will need it in ex. 04

router = APIRouter()

CATEGORIES = ("auto damage", "property damage", "health and life", "liability")
SYSTEM = "You are a claims adjuster's assistant. You answer with one category from the list."

_sync_client = anthropic.Anthropic(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)


def _prompt(n: int) -> str:
    return (f"Categories: {', '.join(CATEGORIES)}.\nClassify the claim:\n"
            f"{data.describe_for_llm(data.claim(n))}")


def _category(text: str, n: int) -> str:
    # the mock returns random words — we pick the category deterministically from the response
    return CATEGORIES[(len(text) + n) % len(CATEGORIES)]


@router.post("/claims/{n}/classify")
async def classify(n: int, request: Request):
    t0 = time.perf_counter()
    m = _sync_client.messages.create(model=config.LLM_MODEL, max_tokens=16, system=SYSTEM,
                                     messages=[{"role": "user", "content": _prompt(n)}],
                                     extra_headers=pipeline.mock_headers(request) or None)   # F1: blocks the loop
    text = "".join(b.text for b in m.content if b.type == "text")
    pipeline.record_outcome(request, "classify", "short", "ok", t0, {"llm": time.perf_counter() - t0})
    return {"claim": data.claim(n)["id"], "category": _category(text, n)}
