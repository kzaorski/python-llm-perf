# Ex. 01 — hint 3 (pseudocode)

```python
from opentelemetry import trace
# in slot(), after acquiring the semaphore, once you know `wait` and `t0_ns`:
s = telemetry.tracer.start_span("llm.queue_wait", start_time=t0_ns,
                                attributes={"app.request_class": request_class})
s.end()
trace.get_current_span().set_attribute("llm.queue.wait_ms", round(wait * 1000, 1))
telemetry.record(telemetry.H_QUEUE_WAIT, wait, request_class=request_class)
```
Restart the application, send a few requests, `python check.py ex01`.
