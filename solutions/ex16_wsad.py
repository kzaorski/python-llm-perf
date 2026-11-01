"""[ROZWIĄZANIE ćw. 16 — kopiuj do app/wsad.py] Ocena priorytetu zgłoszeń wsadowo (batching) — endpoint POST /claims/{n}/priority.

Pojedyncze prośby o priorytet zbieramy we wsad i wysyłamy JEDNO wywołanie LLM dla wielu zgłoszeń:
mniej żądań do dostawcy (limit RPM), wspólny narzut. Ceną jest czekanie na skompletowanie wsadu.

Ćw. 16 (W11): okno 2 s i wsad do 100 zgłoszeń — przy małym ruchu każda prośba czeka pełne okno
(+2 s do latencji), a przy dużym jedno wywołanie niesie 100 zgłoszeń (wejście ~100× większe, długa
generacja; przy limicie tokenów — 429 dla całego wsadu naraz).
✅ ćw. 16: okno 50 ms, wsad ≤ 16 (zmierzone: patrz ćwiczenie).
"""
from __future__ import annotations

import asyncio
import os
import time

from fastapi import APIRouter

from . import dane, obsluga, telemetry
from .llm import Zadanie

router = APIRouter()

# ćw. 16 (W11) ✅: okno rzędu milisekund i mały wsad. Przy ruchu ~20 próśb/s okno 50 ms zbiera ~1–16
# zgłoszeń (redukcja wywołań kilka–kilkanaście razy), a dokłada ≤ 50 ms zamiast 2 s. Wsad ≤ 16 trzyma
# wejście (~16 × 80 tokenów) i generację (~16 × 6 tokenów) krótkie: jeden wolny wsad nie psuje ogona.
OKNO_S = float(os.environ.get("WSAD_OKNO_S", "0.05"))
MAX_WSAD = int(os.environ.get("WSAD_MAX", "16"))
POZIOMY = ("wysoki", "średni", "niski")


class Wsad:
    def __init__(self, okno_s: float, max_rozmiar: int):
        self.okno_s = okno_s
        self.max = max_rozmiar
        self._oczekujace: list[tuple[int, asyncio.Future, float]] = []
        self._timer: asyncio.TimerHandle | None = None

    async def ocen(self, n: int) -> dict:
        fut = asyncio.get_running_loop().create_future()
        self._oczekujace.append((n, fut, time.perf_counter()))
        if len(self._oczekujace) >= self.max:
            self._wyslij()
        elif self._timer is None:
            self._timer = asyncio.get_running_loop().call_later(self.okno_s, self._wyslij)
        return await fut

    def _wyslij(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        wsad, self._oczekujace = self._oczekujace, []
        if wsad:
            asyncio.ensure_future(self._wykonaj(wsad))

    async def _wykonaj(self, wsad: list) -> None:
        t_wys = time.perf_counter()
        telemetry.zapisz(telemetry.H_WSAD, len(wsad))
        opisy = "\n\n".join(f"[{i + 1}] {dane.opis_dla_llm(dane.zgloszenie(n))}" for i, (n, _, _) in enumerate(wsad))
        z = Zadanie(klasa="krotkie", endpoint="priority-wsad", max_tokens=8 * len(wsad) + 16,
                    prompt=f"Oceń priorytet (wysoki/średni/niski) każdego zgłoszenia:\n{opisy}")
        try:
            w = await obsluga.wykonaj(None, z)
        except Exception as e:  # noqa: BLE001 — błąd całego wsadu trafia do każdego czekającego
            for _, fut, _ in wsad:
                if not fut.done():
                    fut.set_exception(e)
            return
        for i, (n, fut, t_we) in enumerate(wsad):
            if not fut.done():
                fut.set_result({"zgloszenie": dane.zgloszenie(n)["id"],
                                "priorytet": POZIOMY[(len(w.tekst) + n + i) % 3],
                                "rozmiar_wsadu": len(wsad),
                                "czekanie_na_wsad_ms": round((t_wys - t_we) * 1000, 1)})


WSAD = Wsad(OKNO_S, MAX_WSAD)


@router.post("/claims/{n}/priority")
async def priorytet(n: int):
    return await WSAD.ocen(n)
