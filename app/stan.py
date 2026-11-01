"""Stan procesu widoczny w metrykach i w /diag: kolejka do LLM per klasa, lag pętli, liczniki wyników.

Moduł infrastruktury pomiaru — działa od startu, nie jest tematem ćwiczeń.
Klasy żądań: `krotkie` (streszczenie, klasyfikacja, FAQ, priorytet; sekundy) i `dlugie`
(analiza dokumentacji szkody; wywołania wielominutowe 60–300 s).
"""
from __future__ import annotations

import itertools
import time
from collections import Counter, deque

KLASY = ("krotkie", "dlugie")


class StanKlasy:
    def __init__(self) -> None:
        self._czekajacy: dict[int, float] = {}
        self._licznik = itertools.count()
        self.w_toku = 0

    def zacznij_czekac(self) -> int:
        tok = next(self._licznik)
        self._czekajacy[tok] = time.monotonic()
        return tok

    def przestan_czekac(self, tok: int) -> None:
        self._czekajacy.pop(tok, None)

    @property
    def liczba_czekajacych(self) -> int:
        return len(self._czekajacy)

    @property
    def wiek_najstarszego(self) -> float:
        if not self._czekajacy:
            return 0.0
        return time.monotonic() - min(self._czekajacy.values())

    def jako_dict(self) -> dict:
        return {"czekajace": self.liczba_czekajacych, "w_toku": self.w_toku,
                "wiek_najstarszego_s": round(self.wiek_najstarszego, 2)}


STAN: dict[str, StanKlasy] = {k: StanKlasy() for k in KLASY}


class Petla:
    """Ostatnie próbki lagu pętli zdarzeń (do /diag)."""

    def __init__(self) -> None:
        self.probki: deque[tuple[float, float]] = deque(maxlen=600)

    def zapisz(self, lag: float) -> None:
        self.probki.append((time.monotonic(), lag))

    def max_ostatnie(self, sekund: float = 10.0) -> float:
        granica = time.monotonic() - sekund
        return max((lag for t, lag in self.probki if t >= granica), default=0.0)


PETLA = Petla()
WYNIKI: Counter = Counter()   # (endpoint, klasa, wynik) -> liczba, od startu procesu
PROBY_HTTP: Counter = Counter()  # (dostawca, status) -> liczba prób HTTP do dostawcy
