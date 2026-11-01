# Ćw. 13 — podpowiedź 3 (pseudokod)

```python
async def generator():
    i = 0
    async for kawalek in klient.strumien(z):
        if i == 0:
            pierwszy_fragment(czasy, t0)
        yield sse("delta", {"tekst": kawalek})
        i += 1
        if i % 20 == 0 and await request.is_disconnected():
            wynik = "anulowane"; return
    yield sse("koniec", {...})
```
`python check.py ex13` (pierwszy `delta` < 30% całości).
