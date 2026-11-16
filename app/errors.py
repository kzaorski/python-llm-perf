"""App exceptions mapped to HTTP responses (app/pipeline.py)."""
from __future__ import annotations


class Rejected(Exception):
    """The app deliberately refuses to serve (full queue, wait too long) → 503 + Retry-After."""

    def __init__(self, reason: str, retry_after: float = 1.0):
        super().__init__(reason)
        self.reason = reason
        self.retry_after = retry_after


class DeadlineExceeded(Exception):
    """The request's total deadline was exceeded → 504."""

    def __init__(self, where: str, after_s: float):
        super().__init__(f"{where}: deadline {after_s:.0f} s")
        self.where = where
        self.after_s = after_s


class ClientDisconnected(Exception):
    """The client disconnected — work aborted, slot released (code 499, as in nginx)."""


class NotImplementedTODO(Exception):
    """The endpoint depends on an exercise you have not done yet → 501 with a hint."""

    def __init__(self, exercise: str, what: str):
        super().__init__(f"ex. {exercise}: {what}")
        self.exercise = exercise
        self.what = what
