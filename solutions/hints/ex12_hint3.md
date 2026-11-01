# Ćw. 12 — podpowiedź 3 (pseudokod)

```python
# przeciazenie.py
MAX_CZEKAJACYCH = {"krotkie": 64, "dlugie": 8}
MAX_CZEKANIA_S = {"krotkie": 5.0, "dlugie": 20.0}
def dopusc(klasa):
    if stan.STAN[klasa].liczba_czekajacych >= MAX_CZEKAJACYCH[klasa]:
        raise Odrzucone("kolejka_pelna", retry_after=MAX_CZEKANIA_S[klasa])
def max_czekania(klasa): return MAX_CZEKANIA_S[klasa]

# limiter.py
def semafor(klasa): return _SEMAFORY[klasa]
```
Wartości progów można brać z env (`KOLEJKA_KROTKIE`, `CZEKANIE_KROTKIE_S` …) — patrz `solutions/ex12_przeciazenie.py`. `python check.py ex12`.
