# Ćw. 08 — podpowiedź 2 (API)

- `limiter.tempo(klasa, max_tokens)` — wołane przed każdym wywołaniem; ma czekać, aż kubełek żądań (RPM)
  i tokenów wyjścia (OTPM, dostawca rezerwuje `max_tokens` na starcie) pozwoli.
- `limiter.aktualizuj_z_naglowkow(status, naglowki)` — wołane po każdej odpowiedzi: zsynchronizuj kubełki z
  `*-limit`/`*-remaining`; przy 429 wstrzymaj wszystkich do `retry-after`.
- Nie czekaj na „sondę”: pierwszą falę i tak trzyma pula slotów. Dowód: `/admin/stats` atrapy (429 ≈ 0),
  `sum by (status) (increase(mock_llm_requests_total{provider="a"}[3m]))`.
