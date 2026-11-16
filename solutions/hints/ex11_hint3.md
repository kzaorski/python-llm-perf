# Ex. 11 — hint 3 (pseudocode)

```python
class CircuitBreaker:
    def should_try_a(self):
        if self.state == "closed": return True
        if self.state == "open" and now() >= self.open_until: self._set_state("half_open")
        if self.state == "half_open" and not self.probe_in_flight:
            self.probe_in_flight = True; return True
        return False
    def success(self): self.failures = 0; self.probe_in_flight = False; self._set_state("closed")
    def failure(self):
        self.failures += 1; self.probe_in_flight = False
        if self.state == "half_open" or self.failures >= FAILURE_THRESHOLD:
            self._set_state("open"); self.open_until = now() + OPEN_DURATION_S
```
In the invoke function: `if cb.should_try_a(): try a → cb.success() / except → cb.failure(), then b`. `python check.py ex11`.
