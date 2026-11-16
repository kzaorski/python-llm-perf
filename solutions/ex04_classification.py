"""[SOLUTION ex. 04 — copy to app/classification.py] Claim classification (type of case) — endpoint POST /claims/{n}/classify.

Ex. 04 (F1): the `async def` handler calls the SYNCHRONOUS `anthropic.Anthropic` client. The call blocks
the event loop for the whole LLM response time: N parallel classifications take ≈ N × t, and during that time
EVERY other endpoint of this process stands still (including /health). The trace shows gaps, the loop lag metric shows it.
✅ ex. 04: the asynchronous path (pipeline.execute).
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from . import data, pipeline
from .llm import LLMJob

router = APIRouter()

CATEGORIES = ("auto damage", "property damage", "health and life", "liability")
SYSTEM = "You are a claims adjuster's assistant. You answer with one category from the list."


def _prompt(n: int) -> str:
    return (f"Categories: {', '.join(CATEGORIES)}.\nClassify the claim:\n"
            f"{data.describe_for_llm(data.claim(n))}")


def _category(text: str, n: int) -> str:
    # the mock returns random words — we pick the category deterministically from the response
    return CATEGORIES[(len(text) + n) % len(CATEGORIES)]


@router.post("/claims/{n}/classify")
async def classify(n: int, request: Request):
    # ex. 04 (F1) ✅: the asynchronous path (AsyncAnthropic through pipeline.execute) — `await` hands
    # the event loop to other requests while waiting for the LLM; you also get the slot, limits, deadline, etc.
    w = await pipeline.execute(request, LLMJob(request_class="short", endpoint="classify", max_tokens=16,
                                               system=SYSTEM, prompt=_prompt(n),
                                               headers=pipeline.mock_headers(request)))
    return {"claim": data.claim(n)["id"], "category": _category(w.text, n)}
