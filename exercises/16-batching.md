# Ćwiczenie 16: Batching — okno i rozmiar wsadu a latencja i przepustowość

> Czas: ~35 min

> Blok V. Czytanka `14a-kolejki-zadan-cache-batching.md` (batching: okno, rozmiar, dwa końce).

## Cel
Ocena priorytetu zgłoszenia (`POST /claims/{n}/priority`) to krótkie zadanie: kilka tokenów wyjścia. Zamiast
wywołania na każde zgłoszenie aplikacja zbiera prośby we wsad i wysyła jedno wywołanie dla wielu zgłoszeń —
mniej żądań do dostawcy (limit RPM, ćw. 08). Okno i rozmiar wsadu dobrano jednak „na oko”. Mierzysz oba końce:
pojedynczą prośbę przy małym ruchu i wsady przy dużym, i dobierasz parametry do SLO.

## Teoria w pigułce
- **Batching** — wspólny narzut (połączenie, prompt systemowy, slot, limit RPM) dzielony przez N zgłoszeń.
  Intuicja: autobus zamiast taksówek. Po co: mniej wywołań przy tym samym ruchu.
- **Okno (`OKNO_S`)** — jak długo czekamy na skompletowanie wsadu. Przy małym ruchu każda prośba czeka
  pełne okno — dokładasz je wprost do latencji.
- **Rozmiar (`MAX_WSAD`)** — górna granica zgłoszeń w jednym wywołaniu. Za duży: wejście ~N× większe, dłuższa
  generacja (czas wywołania rośnie z liczbą tokenów wyjścia), jeden wolny wsad psuje ogon wszystkich N; przy
  limicie tokenów wejścia (ITPM) 429 trafia cały wsad naraz.
- Pułapka: mierzysz tylko przy dużym ruchu (wsady pełne, „działa”) albo tylko pojedynczo — trzeba obu końców.
  Little: przy λ próśb/s okno T zbiera średnio λ·T zgłoszeń.

## Kroki
1. Stan po ćw. 15, aplikacja na 8060. Zajrzyj do **`app/wsad.py`**: `OKNO_S = 2.0`, `MAX_WSAD = 100`.
2. **Hipoteza:** ile potrwa jedna prośba o priorytet, gdy nikt inny nie pyta? A 30 równoczesnych — ile
   wsadów, jakiej wielkości?
3. Oba końce:
   ```bash
   curl -s -w '  [%{time_total} s]\n' -X POST 127.0.0.1:8060/claims/7/priority
   seq 30 | xargs -P 30 -I{} curl -s -X POST 127.0.0.1:8060/claims/{}/priority | python -c "import sys,json; r=[json.loads(l) for l in sys.stdin.read().replace('}{','}\n{').splitlines() if l.strip()]; print('odpowiedzi', len(r), 'rozmiary wsadów', sorted({x['rozmiar_wsadu'] for x in r}), 'czekanie max ms', max(x['czekanie_na_wsad_ms'] for x in r))"
   ```
   Prometheus — średni rozmiar wsadu od startu procesu (histogram jest liczony od uruchomienia aplikacji;
   `rate()`/`increase()` po świeżym restarcie nie policzą pierwszej serii próbek, a kwantyl z kilku wsadów to
   tylko interpolacja kubełków):
   ```
   sum(app_batch_size_sum) / sum(app_batch_size_count)
   ```
   U mnie: pojedyncza prośba **2.56 s** (`czekanie_na_wsad_ms` 2001.6 — całe okno), 30 równoczesnych → jeden
   wsad **30**, czekanie max 2002 ms; średni wsad 15.5.
4. W Tempo otwórz ślad jednej prośby: ile z czasu to czekanie na wsad, ile `llm.call`?
5. **Dobór parametrów (W11).** W **`app/wsad.py`** (`TODO ćw. 16`) zmień `OKNO_S` i `MAX_WSAD`. Kryteria:
   pojedyncza prośba < 1.2 s (okno nie może dominować latencji), przy ruchu ~20–30 próśb/s wsad > 1 (bo inaczej
   batching nic nie daje) i mały (krótka generacja). Policz z Little'a, ile zgłoszeń zbierze okno 50 ms przy 30/s.
6. Restart, powtórka kroku 3. U mnie: pojedyncza **0.79 s** (czekanie na wsad 53 ms), 30 równoczesnych →
   wsady **14 i 16**, czekanie max 50 ms; `check.py ex16`: pojedyncza 0.60 s, wsad max 16.

   U mnie (okno 2 s / wsad 100 → 50 ms / 16): pojedyncza prośba **2.78 s → 0.54 s**; ruch otwarty 30/s × 10 s:
   wsady ~60, 5 wywołań, p99 4.50 s → wsady p50 2 / max 5, 146 wywołań, p99 1.14 s.
7. `python check.py ex16`

## Kryteria „done”
- [ ] Pojedyncza prośba < 1.2 s; przy 30 równoczesnych wsad > 1 i ≤ 32.
- [ ] Umiesz podać koszt i zysk swojego okna: ile ms dokłada, ile razy zmniejsza liczbę wywołań.
- [ ] `python check.py ex16` przechodzi.

## Pytania kontrolne
1. Po zmianie liczba wywołań LLM wzrosła z 5 do 146. Dlaczego to dobry wynik? Kiedy byłby zły?
2. Dostawca ma limit ITPM. Co dzieje się z wsadem 100 zgłoszeń, gdy zostało 20% limitu, a co z wsadem 5?
3. Jak dobrać okno, gdy SLO priorytetu to p99 < 1 s, a ruch zmienia się w ciągu dnia od 0.1/s do 50/s?

Odpowiedzi: `solutions/pytania_odpowiedzi.md`.

## ★ Bonus (opcjonalnie)
Okno adaptacyjne: wysyłaj natychmiast, jeśli od poprzedniego wsadu minęło > X ms i nikt nie czeka; zbieraj
dopiero, gdy wywołanie jest w toku (wsad „z tego, co narosło w trakcie”). Porównaj oba końce z wersją stałego okna.

---
Utknąłeś? `solutions/hints/ex16_hint1.md` → `hint2` → `hint3`. Gotowe rozwiązanie:
`solutions/ex16_wsad.py` → `app/wsad.py`.
