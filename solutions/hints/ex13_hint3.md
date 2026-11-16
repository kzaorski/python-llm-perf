# Ex. 13 — hint 3 (pseudocode)

```python
async def generate():
    i = 0
    async for chunk in client.stream(job):
        if i == 0:
            first_chunk(timings, t0)
        yield sse("delta", {"text": chunk})
        i += 1
        if i % 20 == 0 and await request.is_disconnected():
            outcome = "cancelled"; return
    yield sse("end", {...})
```
`python check.py ex13` (the first `delta` < 30% of the total).
