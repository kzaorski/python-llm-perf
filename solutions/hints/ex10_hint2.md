# Ćw. 10 — podpowiedź 2 (API / metryki)

- `anthropic.Timeout(connect=3, read=15, write=10, pool=5)` dla krótkich; długie: strumień, `read=60`,
  `max_retries=0` (ping dostawcy co 15 s utrzymuje połączenie).
- Deadline: `async with asyncio.timeout(DEADLINE_S[klasa])` wokół wywołania → `Przeterminowane` (504).
- Rozłączenie: zadanie-strażnik `while not await request.is_disconnected(): await asyncio.sleep(0.5)`;
  `asyncio.wait({praca, straz}, return_when=FIRST_COMPLETED)`; gdy pierwszy skończy strażnik — `praca.cancel()`.
- Dowód: `sum by (phase) (increase(mock_llm_cancelled_total[10m]))`, `/admin/stats` (`generating`,
  `oldest_inflight_s`), `/diag` → `klienci` (timeouty, `max_retries`). Aplikację uruchamiaj z `LLM_FALLBACK=0`.
