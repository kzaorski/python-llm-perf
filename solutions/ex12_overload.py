"""[SOLUTION ex. 12 — copy to app/overload.py] Backpressure and load shedding.

Ex. 12 ✅ (F7, F8):
- F7: a queue limit per class — when MAX_WAITING are already waiting, a new request gets an immediate 503
  + Retry-After (milliseconds instead of minutes; the client can retry later or go elsewhere);
- F8: a wait budget per class — whoever did not get a slot within MAX_WAIT_S gets a 503 instead of waiting
  longer (their client would have given up anyway; work after the deadline is wasted work).
Values from Little's law: the short queue ≈ throughput × acceptable wait
(32 slots / ~1.6 s ≈ 20/s × 2 s ≈ 40 → 64 with headroom); long: 8 in the queue, max 20 s of waiting.
"""
from __future__ import annotations

import os

from . import state
from .errors import Rejected

MAX_WAITING = {"short": int(os.environ.get("QUEUE_SHORT", "64")),
               "long": int(os.environ.get("QUEUE_LONG", "8"))}
MAX_WAIT_S = {"short": float(os.environ.get("WAIT_SHORT_S", "5")),
              "long": float(os.environ.get("WAIT_LONG_S", "20"))}


def admit(request_class: str) -> None:
    if state.STATE[request_class].waiting_count >= MAX_WAITING[request_class]:
        raise Rejected("queue_full", retry_after=MAX_WAIT_S[request_class])


def max_wait(request_class: str) -> float | None:
    return MAX_WAIT_S[request_class]
