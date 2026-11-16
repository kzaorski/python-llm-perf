"""Process state visible in the metrics and in /diag: the LLM queue per class, event loop lag, outcome counters.

A measurement infrastructure module — it works from startup and is not a subject of the exercises.
Request classes: `short` (summary, classification, FAQ, priority; seconds) and `long`
(claim file analysis; multi-minute calls of 60–300 s).
"""
from __future__ import annotations

import itertools
import time
from collections import Counter, deque

REQUEST_CLASSES = ("short", "long")


class ClassState:
    def __init__(self) -> None:
        self._waiting: dict[int, float] = {}
        self._counter = itertools.count()
        self.inflight = 0

    def start_waiting(self) -> int:
        tok = next(self._counter)
        self._waiting[tok] = time.monotonic()
        return tok

    def stop_waiting(self, tok: int) -> None:
        self._waiting.pop(tok, None)

    @property
    def waiting_count(self) -> int:
        return len(self._waiting)

    @property
    def oldest_age(self) -> float:
        if not self._waiting:
            return 0.0
        return time.monotonic() - min(self._waiting.values())

    def as_dict(self) -> dict:
        return {"waiting": self.waiting_count, "inflight": self.inflight,
                "oldest_age_s": round(self.oldest_age, 2)}


STATE: dict[str, ClassState] = {k: ClassState() for k in REQUEST_CLASSES}


class LoopLag:
    """Recent event loop lag samples (for /diag)."""

    def __init__(self) -> None:
        self.samples: deque[tuple[float, float]] = deque(maxlen=600)

    def record(self, lag: float) -> None:
        self.samples.append((time.monotonic(), lag))

    def recent_max(self, seconds: float = 10.0) -> float:
        cutoff = time.monotonic() - seconds
        return max((lag for t, lag in self.samples if t >= cutoff), default=0.0)


LOOP_LAG = LoopLag()
OUTCOMES: Counter = Counter()   # (endpoint, request_class, outcome) -> count, since process start
HTTP_ATTEMPTS: Counter = Counter()  # (provider, status) -> number of HTTP attempts to the provider
