# Ćw. 01 — podpowiedź 2 (API)

- `telemetry.tracer.start_span("llm.queue_wait", start_time=t0_ns)` + `.end()` — span z przeszłym początkiem,
  **bez** `start_as_current_span` (nie aktywuje kontekstu → nie zostaje rodzicem kolejnych spanów).
- `opentelemetry.trace.get_current_span().set_attribute("llm.queue.wait_ms", …)` — span żądania (korzeń z FastAPI).
- `telemetry.zapisz(telemetry.H_CZEKANIE, czekanie, klasa=klasa)` — histogram `llm_queue_wait_seconds{klasa}`.

Sprawdzenie: TraceQL `{name="llm.queue_wait"}` i `{span.llm.queue.wait_ms > 100.0}` (z `.0` — atrybut jest float).
