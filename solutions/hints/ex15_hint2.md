# Ćw. 15 — podpowiedź 2 (API)

- W procesie: `_w_toku: dict[str, asyncio.Future]`; pierwszy tworzy `loop.create_future()`, reszta
  `await asyncio.shield(fut)` (shield: anulowanie jednego czekającego nie anuluje wspólnego wyniku).
- Między procesami: `await r.set(k + ":blokada", "1", nx=True, px=30_000)` — kto nie zdobył, odpytuje `r.get(k)`
  co 50 ms.
- Licznik: `telemetry.zapisz(telemetry.C_CACHE, 1, wynik="wspolne")`; zapytanie
  `sum by (wynik) (increase(app_cache_total[2m]))`.
- Błąd właściciela: `fut.set_exception(e)` — inaczej czekający wiszą.
