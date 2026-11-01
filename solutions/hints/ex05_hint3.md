# Ćw. 05 — podpowiedź 3 (pseudokod)

```python
@router.post("/claims/{n}/letter")
async def pismo(n: int, request: Request):
    z = dane.zgloszenie(n)
    w = await klient.zapytaj(Zadanie(klasa="krotkie", endpoint="letter", max_tokens=300,
                                     prompt=_prompt(z), naglowki=obsluga.naglowki_atrapy(request)))
    return {... jak wcześniej, z w.tekst ...}
```
`python check.py ex05` — 60 odpowiedzi w jednej fali.
