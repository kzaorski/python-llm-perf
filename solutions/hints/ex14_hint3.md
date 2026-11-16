# Ex. 14 — hint 3 (pseudocode)

```python
G_LAG = Gauge("queue_lag", "..."); G_PENDING = Gauge("queue_pending", "...")
G_AGE = Gauge("queue_oldest_age_seconds", "...")

async def sample(r):
    group = next((g for g in await r.xinfo_groups(STREAM) if g["name"] == GROUP), None)
    lag = pending = 0; age = 0.0
    if group:
        lag, pending = int(group["lag"] or 0), int(group["pending"] or 0)
        next_entry = await r.xrange(STREAM, min="(" + group["last-delivered-id"], max="+", count=1)
        if next_entry: age = time.time() - int(next_entry[0][0].split("-")[0]) / 1000
    G_LAG.set(lag); G_PENDING.set(pending); G_AGE.set(age)
```
Handle a missing stream/group (`ResponseError`) — the exporter has to work before the worker starts. `python check.py ex14`.
