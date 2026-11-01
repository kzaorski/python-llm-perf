# Ćw. 11 — podpowiedź 3 (pseudokod)

```python
class Wylacznik:
    def czy_pytac_a(self):
        if self.stan == "zamkniety": return True
        if self.stan == "otwarty" and now() >= self.otwarty_do: self._ustaw("polotwarty")
        if self.stan == "polotwarty" and not self.probka_w_toku:
            self.probka_w_toku = True; return True
        return False
    def sukces(self): self.awarie = 0; self.probka_w_toku = False; self._ustaw("zamkniety")
    def awaria(self):
        self.awarie += 1; self.probka_w_toku = False
        if self.stan == "polotwarty" or self.awarie >= PROG_AWARII:
            self._ustaw("otwarty"); self.otwarty_do = now() + CZAS_OTWARCIA_S
```
W funkcji wywołania: `if cb.czy_pytac_a(): try a → cb.sukces() / except → cb.awaria(), potem b`. `python check.py ex11`.
