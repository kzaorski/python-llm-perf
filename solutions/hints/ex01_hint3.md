# Ćw. 01 — podpowiedź 3 (pseudokod)

```python
from opentelemetry import trace
# w slot(), po zdobyciu semafora, gdy znasz `czekanie` i `t0_ns`:
s = telemetry.tracer.start_span("llm.queue_wait", start_time=t0_ns,
                                attributes={"app.klasa": klasa})
s.end()
trace.get_current_span().set_attribute("llm.queue.wait_ms", round(czekanie * 1000, 1))
telemetry.zapisz(telemetry.H_CZEKANIE, czekanie, klasa=klasa)
```
Restart aplikacji, kilka żądań, `python check.py ex01`.
