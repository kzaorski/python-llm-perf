# Ćw. 08 — podpowiedź 3 (pseudokod)

```python
class Kubelek:          # limit/min, poziom, czas ostatniego uzupełnienia
    def czas_do(n): ...  # ile sekund do n tokenów
    def zabierz(n): ...
    def synchronizuj(limit, pozostalo): ...  # poziom = min(poziom, pozostalo)

async def tempo(klasa, max_tokens):
    async with _kolejnosc:                     # FIFO
        while True:
            czekaj = max(_pauza_do - now(), RPM.czas_do(1), OTPM.czas_do(max_tokens))
            if czekaj <= 0: RPM.zabierz(1); OTPM.zabierz(max_tokens); return
            await asyncio.sleep(min(czekaj, 1.0))
```
`python check.py ex08` (profil `limity`, 90 naraz → 429 ≤ 1%).
