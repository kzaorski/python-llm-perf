# Ex. 01 — hint 2 (API)

- `telemetry.tracer.start_span("llm.queue_wait", start_time=t0_ns)` + `.end()` — a span with a start in the past,
  **without** `start_as_current_span` (it does not activate the context → it does not become the parent of later spans).
- `opentelemetry.trace.get_current_span().set_attribute("llm.queue.wait_ms", …)` — the request span (the root from FastAPI).
- `telemetry.record(telemetry.H_QUEUE_WAIT, wait, request_class=request_class)` — the histogram `llm_queue_wait_seconds{request_class}`.

Check: TraceQL `{name="llm.queue_wait"}` and `{span.llm.queue.wait_ms > 100.0}` (with `.0` — the attribute is a float).
