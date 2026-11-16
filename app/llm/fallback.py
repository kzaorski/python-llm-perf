"""Fallback provider a → b.

Ex. 11 (F12): when `a` fails, EVERY request first pays the full cost of the failure at `a` (e.g. a timeout)
and only then goes to `b`. There is no circuit breaker: we do not remember that `a` is down.
TODO ex. 11: a circuit breaker — states closed → open (after N failures) → half-open (a probe request after a while).
"""
from __future__ import annotations

import anthropic

from .. import config
from . import LLMJob, LLMResult, client

# Errors after which it is worth trying another provider: an outage/hang, not "too much traffic".
OUTAGE_ERRORS = (anthropic.APIConnectionError, anthropic.InternalServerError)


def _is_outage(e: Exception) -> bool:
    if isinstance(e, anthropic.OverloadedError):
        return False   # 529 overloaded = overload, not an outage — a fallback would move the storm to `b`
    return isinstance(e, OUTAGE_ERRORS)


async def invoke(z: LLMJob) -> LLMResult:
    try:
        return await client.complete(z, "a")
    except Exception as e:
        if not (config.LLM_FALLBACK and _is_outage(e)):
            raise
    return await client.complete(z, "b")
