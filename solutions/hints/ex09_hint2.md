# Ćw. 09 — podpowiedź 2 (API)

- Jedna warstwa: w `app/llm/klient.py` klient krótkich z `max_retries=0`; ponowienia tylko w
  `app/llm/ponowienia.py`.
- Przerwa: pełny jitter `random.uniform(0, min(LIMIT_S, BAZA_S * 2**proba))`; gdy jest `retry-after` — on ma
  pierwszeństwo.
- Budżet: ponowienia ≤ ~20% żądań w oknie 10 s — przy masowej awarii nie mnożysz ruchu.
- Co ponawiać: `RateLimitError`, `OverloadedError` (529 — NIE jest podklasą `InternalServerError`!),
  `InternalServerError`, `APIConnectionError`; **nie** timeouty (`APITimeoutError` ⊂ `APIConnectionError`).
