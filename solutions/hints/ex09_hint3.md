# Ćw. 09 — podpowiedź 3 (pseudokod)

```python
async def z_ponowieniami(fn):
    for proba in range(PROBY):
        try:
            return await fn()
        except Exception as e:
            if proba == PROBY - 1 or not _do_ponowienia(e) or not _budzet_pozwala():
                raise
            _ponowienia.append(now())
            await asyncio.sleep(_przerwa(e, proba))   # retry-after albo U(0, min(8, 0.5·2^p))
```
`_do_ponowienia`: najpierw `if isinstance(e, (APITimeoutError, httpx2.TimeoutException)): return False`.
`python check.py ex09` (≤ 1.5 próby na żądanie przy `przeciazenie`).
