"""Request admission: backpressure and load shedding.

Ex. 12 — TODO (F7, F8):
- F7: the LLM queue has no limit — every request joins the queue, even when 500 others are waiting ahead of it;
  the age of the oldest grows without bound, and responses arrive after minutes (or nobody is waiting for them anymore);
- F8: no wait budget — there is no fast 503 for part of the traffic; everyone waits long.

app/pipeline.py calls:  overload.admit(request_class)  and  limiter.slot(..., max_wait=overload.max_wait(request_class))
"""
from __future__ import annotations


def admit(request_class: str) -> None:
    """TODO ex. 12 (F7): raise errors.Rejected when too many requests are already waiting in the class queue (state.STATE)."""
    return None


def max_wait(request_class: str) -> float | None:
    """TODO ex. 12 (F8): how many seconds a request of the class may wait for a slot before getting a 503 (None = no limit)."""
    return None
