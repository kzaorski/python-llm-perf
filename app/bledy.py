"""Wyjątki aplikacji mapowane na odpowiedzi HTTP (app/obsluga.py)."""
from __future__ import annotations


class Odrzucone(Exception):
    """Aplikacja świadomie odmawia obsługi (pełna kolejka, za długie czekanie) → 503 + Retry-After."""

    def __init__(self, powod: str, retry_after: float = 1.0):
        super().__init__(powod)
        self.powod = powod
        self.retry_after = retry_after


class Przeterminowane(Exception):
    """Przekroczony deadline całkowity żądania → 504."""

    def __init__(self, gdzie: str, po_s: float):
        super().__init__(f"{gdzie}: deadline {po_s:.0f} s")
        self.gdzie = gdzie
        self.po_s = po_s


class Anulowane(Exception):
    """Klient się rozłączył — praca przerwana, slot zwolniony (kod 499, jak w nginx)."""


class NiezaimplementowaneTODO(Exception):
    """Endpoint zależy od niezrobionego ćwiczenia → 501 z podpowiedzią."""

    def __init__(self, cwiczenie: str, co: str):
        super().__init__(f"ćw. {cwiczenie}: {co}")
        self.cwiczenie = cwiczenie
        self.co = co
