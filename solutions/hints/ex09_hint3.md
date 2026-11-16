# Ex. 09 — hint 3 (pseudocode)

```python
async def with_retries(fn):
    for attempt in range(ATTEMPTS):
        try:
            return await fn()
        except Exception as e:
            if attempt == ATTEMPTS - 1 or not _should_retry(e) or not _budget_allows():
                raise
            _retries.append(now())
            await asyncio.sleep(_pause(e, attempt))   # retry-after or U(0, min(8, 0.5·2^p))
```
`_should_retry`: first `if isinstance(e, (APITimeoutError, httpx2.TimeoutException)): return False`.
`python check.py ex09` (≤ 1.5 attempts per request with `overload`).
