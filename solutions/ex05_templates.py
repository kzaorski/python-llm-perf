"""[SOLUTION ex. 05 — copy to app/templates.py] Customer letters from templates — endpoint POST /claims/{n}/letter.

The "templates" module is synchronous (rendering + a synchronous LLM client), so the handler is
a plain `def`. FastAPI runs such handlers in the anyio thread pool, whose limit is 40 threads.

Ex. 05 (F2): with > 40 concurrent requests the excess waits for a free thread — without using CPU,
leaving no trace in the app code; the response time grows in steps every ~40 requests.
✅ ex. 05: `async def` + client.complete (AsyncAnthropic).
"""
from __future__ import annotations

import time
from string import Template

from fastapi import APIRouter, Request

from . import data, pipeline
from .llm import LLMJob, client

router = APIRouter()

TEMPLATE = Template("Dear $customer,\n\nregarding claim $id (policy $policy), "
                    "we are writing to let you know:\n$body\n\nSincerely,\nClaims Department")


def _prompt(z: dict) -> str:
    return f"Write a short, polite note about the next steps of the claim settlement.\n{data.describe_for_llm(z)}"


def render(z: dict, body: str) -> str:
    return TEMPLATE.substitute(customer=z["customer"], id=z["id"], policy=z["policy"], body=body.strip())


@router.post("/claims/{n}/letter")
async def letter(n: int, request: Request):
    # ex. 05 (F2) ✅: `async def` + AsyncAnthropic — the request does not occupy a thread from the anyio pool (40)
    # while waiting for the LLM. Rendering the template is fast (µs of CPU), so it can stay in the loop.
    t0 = time.perf_counter()
    z = data.claim(n)
    w = await client.complete(LLMJob(request_class="short", endpoint="letter", max_tokens=300, prompt=_prompt(z),
                                     headers=pipeline.mock_headers(request)))
    pipeline.record_outcome(request, "letter", "short", "ok", t0, {"llm": w.duration_s})
    return {"claim": z["id"], "letter": render(z, w.text)}
