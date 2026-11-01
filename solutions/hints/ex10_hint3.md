# Ćw. 10 — podpowiedź 3 (pseudokod)

```python
async def z_deadlinem(request, klasa, fn):
    praca = asyncio.ensure_future(fn())
    straz = asyncio.ensure_future(_czekaj_na_rozlaczenie(request)) if request else None
    try:
        async with asyncio.timeout(DEADLINE_S[klasa]):
            await asyncio.wait({praca} | ({straz} if straz else set()), return_when=FIRST_COMPLETED)
    except TimeoutError:
        praca.cancel(); await suppress(praca); raise Przeterminowane(...)
    finally:
        if straz: straz.cancel()
    if praca.done(): return praca.result()
    praca.cancel(); await suppress(praca); raise Anulowane()
```
Plus w `klient.py`: długie przez `messages.stream(...)` (TTFT z pierwszego zdarzenia). `python check.py ex10`.
