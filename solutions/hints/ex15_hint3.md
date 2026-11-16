# Ex. 15 — hint 3 (pseudocode)

```python
v = await r.get(k)
if v: return v, "hit"
if k in _inflight: return await asyncio.shield(_inflight[k]), "shared"
fut = loop.create_future(); _inflight[k] = fut
try:
    if await r.set(k + ":lock", "1", nx=True, px=LOCK_MS):
        try: v = await compute(q, request); await r.set(k, v, ex=TTL_S)
        finally: await r.delete(k + ":lock")
    else:
        v = await wait_for_cache(k)        # or compute it yourself after the lock time
    fut.set_result(v); return v, ...
except BaseException as e:
    if not fut.done(): fut.set_exception(e); fut.exception()
    raise
finally:
    _inflight.pop(k, None)
```
`python check.py ex15` (50 questions → 1 call).
