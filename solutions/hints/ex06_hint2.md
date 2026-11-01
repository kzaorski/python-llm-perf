# Ćw. 06 — podpowiedź 2 (metryki)

- `max_over_time(llm_inflight{klasa="krotkie"}[2m])` przyklejone do 4; `llm_waiting` i
  `llm_oldest_waiting_age_seconds` rosną; histogram `llm_queue_wait_seconds`; `/diag` → `kolejka`.
- Druga strona: `max_over_time(mock_llm_generating{provider="a"}[2m])` — ile generacji naraz widzi dostawca.
  Gdy semafor jest duży, a pula httpx2 mała (`LLM_POLACZENIA=8`), atrapa widzi ≤ 8, a czekanie w puli
  NIE trafia do `llm.queue_wait` (i z pool timeoutem kończy się `APITimeoutError` — PoolTimeout).
