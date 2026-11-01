# Ćw. 04 — podpowiedź 3 (pseudokod)

```python
@router.post("/claims/{n}/classify")
async def klasyfikuj(n: int, request: Request):
    z = Zadanie(klasa="krotkie", endpoint="classify", max_tokens=16, system=SYSTEM,
                prompt=_prompt(n), naglowki=obsluga.naglowki_atrapy(request))
    w = await obsluga.wykonaj(request, z)
    return {"zgloszenie": dane.zgloszenie(n)["id"], "kategoria": _kategoria(w.tekst, n)}
```
Usuń `_klient_sync` i ręczne `zapisz_wynik` (robi to `obsluga.wykonaj`). `python check.py ex04`.
