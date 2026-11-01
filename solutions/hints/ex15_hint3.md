# Ćw. 15 — podpowiedź 3 (pseudokod)

```python
v = await r.get(k)
if v: return v, "hit"
if k in _w_toku: return await asyncio.shield(_w_toku[k]), "wspolne"
fut = loop.create_future(); _w_toku[k] = fut
try:
    if await r.set(k + ":blokada", "1", nx=True, px=BLOKADA_MS):
        try: v = await policz(q, request); await r.set(k, v, ex=TTL_S)
        finally: await r.delete(k + ":blokada")
    else:
        v = await poczekaj_na_cache(k)        # albo policz sam po czasie blokady
    fut.set_result(v); return v, ...
except BaseException as e:
    if not fut.done(): fut.set_exception(e); fut.exception()
    raise
finally:
    _w_toku.pop(k, None)
```
`python check.py ex15` (50 pytań → 1 wywołanie).
