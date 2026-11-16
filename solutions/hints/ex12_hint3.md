# Ex. 12 — hint 3 (pseudocode)

```python
# overload.py
MAX_WAITING = {"short": 64, "long": 8}
MAX_WAIT_S = {"short": 5.0, "long": 20.0}
def admit(request_class):
    if state.STATE[request_class].waiting_count >= MAX_WAITING[request_class]:
        raise Rejected("queue_full", retry_after=MAX_WAIT_S[request_class])
def max_wait(request_class): return MAX_WAIT_S[request_class]

# limiter.py
def semaphore(request_class): return _SEMAPHORES[request_class]
```
The threshold values can come from env (`QUEUE_SHORT`, `WAIT_SHORT_S` …) — see `solutions/ex12_overload.py`. `python check.py ex12`.
