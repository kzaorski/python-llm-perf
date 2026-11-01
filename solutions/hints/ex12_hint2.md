# Ćw. 12 — podpowiedź 2 (API / metryki)

- `app/llm/limiter.py`: słownik semaforów `{"krotkie": Semaphore(SLOTY), "dlugie": Semaphore(SLOTY_DLUGIE)}`,
  `SLOTY_DLUGIE = int(os.environ.get("LLM_SLOTY_DLUGIE", "16"))`; suma ≤ moc dostawcy.
- `app/przeciazenie.py`: `dopusc(klasa)` → `raise Odrzucone("kolejka_pelna", retry_after=…)` gdy czeka już
  `MAX_CZEKAJACYCH[klasa]` (64/8); `max_czekania(klasa)` → 5 s / 20 s (limiter rzuca `Odrzucone` po przekroczeniu).
- Obserwuj: `max by (klasa) (llm_waiting)`, `max by (klasa) (llm_oldest_waiting_age_seconds)`,
  `sum by (klasa, wynik) (increase(app_requests_total[5m]))`; po przebiegu `wyniki/*-przebieg.json`.
