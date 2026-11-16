"""Customer letters from templates — endpoint POST /claims/{n}/letter.

The "templates" module is synchronous (rendering + a synchronous LLM client), so the handler is
a plain `def`. FastAPI runs such handlers in the anyio thread pool, whose limit is 40 threads.

Ex. 05 (F2): with > 40 concurrent requests the excess waits for a free thread — without using CPU,
leaving no trace in the app code; the response time grows in steps every ~40 requests.
TODO ex. 05: an `async def` handler + an asynchronous client (app/llm/client.py: `client.complete`).
"""
from __future__ import annotations

import time
from string import Template

import anthropic
from fastapi import APIRouter, Request

from . import config, data, pipeline

router = APIRouter()

TEMPLATE = Template("Dear $customer,\n\nregarding claim $id (policy $policy), "
                    "we are writing to let you know:\n$body\n\nSincerely,\nClaims Department")

_sync_client = anthropic.Anthropic(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)


def _prompt(z: dict) -> str:
    return f"Write a short, polite note about the next steps of the claim settlement.\n{data.describe_for_llm(z)}"


def render(z: dict, body: str) -> str:
    return TEMPLATE.substitute(customer=z["customer"], id=z["id"], policy=z["policy"], body=body.strip())


@router.post("/claims/{n}/letter")
def letter(n: int, request: Request):   # F2: `def` → the anyio thread pool (40)
    t0 = time.perf_counter()
    z = data.claim(n)
    m = _sync_client.messages.create(model=config.LLM_MODEL, max_tokens=300,
                                     messages=[{"role": "user", "content": _prompt(z)}],
                                     extra_headers=pipeline.mock_headers(request) or None)
    text = "".join(b.text for b in m.content if b.type == "text")
    pipeline.record_outcome(request, "letter", "short", "ok", t0, {"llm": time.perf_counter() - t0})
    return {"claim": z["id"], "letter": render(z, text)}
