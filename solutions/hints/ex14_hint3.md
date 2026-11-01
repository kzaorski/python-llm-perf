# Ćw. 14 — podpowiedź 3 (pseudokod)

```python
G_LAG = Gauge("kolejka_lag", "..."); G_PENDING = Gauge("kolejka_pending", "...")
G_WIEK = Gauge("kolejka_wiek_najstarszego_s", "...")

async def probkuj(r):
    grupa = next((g for g in await r.xinfo_groups(STRUMIEN) if g["name"] == GRUPA), None)
    lag = pending = 0; wiek = 0.0
    if grupa:
        lag, pending = int(grupa["lag"] or 0), int(grupa["pending"] or 0)
        nast = await r.xrange(STRUMIEN, min="(" + grupa["last-delivered-id"], max="+", count=1)
        if nast: wiek = time.time() - int(nast[0][0].split("-")[0]) / 1000
    G_LAG.set(lag); G_PENDING.set(pending); G_WIEK.set(wiek)
```
Obsłuż brak strumienia/grupy (`ResponseError`) — eksporter ma działać przed startem workera. `python check.py ex14`.
