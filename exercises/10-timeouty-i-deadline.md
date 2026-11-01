# Ćwiczenie 10: Timeouty, deadline i anulowanie — wywołania, które trwają minutami

> Czas: ~80 min, w tym ~15 min testów wielominutowych (każdy scenariusz 1–5 min, przed i po naprawie)

> Blok III. Czytanka `08a-limity-retry-timeouty.md` (timeout per operacja vs deadline całkowity,
> wolny pierwszy token, anulowanie); `00-teoria.md` „Wywołania wielominutowe”.

## Cel
Analiza dokumentacji szkody (`POST /claims/{n}/analysis`, klasa „długie”) trwa u dostawcy 60–300 s.
Sprawdzasz trzy rzeczy, które przy takich wywołaniach psują się po cichu: (1) timeout krótszy niż
oczekiwany czas odpowiedzi + ponowienia SDK, (2) brak anulowania, gdy klient zrezygnuje, (3) brak
sensownego timeoutu dla krótkich, gdy dostawca zawiśnie. Każdy scenariusz puszczasz naprawdę —
kilka minut zegara — i patrzysz, co w tym czasie dzieje się ze slotami, z kolejką i u dostawcy.

## Teoria w pigułce
- **Timeout SDK to limity PER OPERACJA, nie czas całkowity.** `timeout=60` w kliencie anthropic/httpx2
  to: połączenie ≤ 60 s, KAŻDY odczyt ≤ 60 s itd. Odczyt resetuje zegar — strumień 150 s przy
  `read=30 s` kończy się poprawnie. Pułapka: „timeout 60 s” nie gwarantuje, że żądanie skończy się w 60 s.
- **Bez strumienia read = czas do CAŁEJ odpowiedzi.** Wywołanie non-stream milczy, aż dostawca skończy
  generować. Analiza 120 s przy `read=60` zawsze kończy się timeoutem — a SDK z `max_retries=2` ponawia
  ją dwa razy: użytkownik czeka ~3 × 60 s na błąd, dostawca zaczyna 3 generacje (koszt ×3).
- **Strumień + ping** — przy strumieniu read timeout staje się limitem BEZCZYNNOŚCI między zdarzeniami
  (tokeny albo `ping`, które dostawca wysyła w ciszy co ~15 s). Pułapka: timeout W TRAKCIE strumienia
  to surowy `httpx2.ReadTimeout`, nie `anthropic.APITimeoutError` — `except APITimeoutError` go nie złapie.
- **Deadline całkowity** — `asyncio.timeout(...)` wokół całej pracy w aplikacji; po przekroczeniu
  zadanie jest anulowane, połączenie z dostawcą zamknięte, a dostawca przerywa generację. To jedyne
  miejsce, gdzie ustalasz „najdłużej X sekund”.
- **Anulowanie po rozłączeniu** — gdy klient (przeglądarka, proxy, k6) zrezygnuje, praca dla niego to
  czysta strata: slot semafora, slot u dostawcy, tokeny. Trzeba to wykryć (`request.is_disconnected()`)
  i anulować wywołanie. Pułapka: middleware `@app.middleware("http")` (BaseHTTPMiddleware) w Starlette
  psuje wykrywanie rozłączenia — aplikacja kursu ma middleware napisane jako czyste ASGI.
- **Łańcuch timeoutów** — klient zewnętrzny > deadline aplikacji > timeouty SDK. k6 ma domyślnie 60 s
  na żądanie (skrypty kursu ustawiają więcej), gunicorn `-k sync` 30 s (ćw. 7). Celowo krótki timeout
  powinien dawać czytelny objaw (504 z przyczyną), a nie przypadkowo unieważniać test.

## Kroki
**Przygotowanie.** W tym ćwiczeniu uruchamiaj aplikację z wyłączonym zapasowym dostawcą — inaczej
zawieszenie `a` dubluje się na `b` i liczby są nieczytelne (fallback to ćw. 11):
```bash
LLM_FALLBACK=0 uvicorn app.main:app --port 8060
```
Obserwuj w trakcie każdego testu (Grafana → Prometheus, odświeżanie 5 s):
```
max_over_time(mock_llm_generating{provider="a"}[10m])
sum by (phase) (increase(mock_llm_cancelled_total[10m]))
max_over_time(mock_llm_oldest_inflight_seconds[10m])
```
albo w terminalu (Ctrl+C kończy):
```bash
while true; do curl -s 127.0.0.1:8061/admin/stats | python -c "import json,sys; a=json.load(sys.stdin)['a']; print(a['generating'], a['waiting'], a['oldest_inflight_s'], a['responses'])"; sleep 2; done
```

### A. Analiza dłuższa niż timeout (W17) — ~3 min przed, ~2 min po
1. Zajrzyj do `curl -s 127.0.0.1:8060/diag | python -m json.tool` → `klienci.dlugie`: `max_retries` i `timeout`.
2. Dostawca: 90 s ciszy przed pierwszym tokenem, potem 30 s generacji; w ciszy wysyła `ping` co 15 s:
   ```bash
   curl -s -X PATCH '127.0.0.1:8061/admin/config?provider=a' -H 'content-type: application/json' \
     -d '{"early_start": true, "ping_interval_s": 15}'
   ```
3. **Hipoteza:** 4 analizy naraz. Kiedy i z jakim statusem skończy się każda? Ile generacji zacznie dostawca?
   ```bash
   python scripts/pomiar.py ex10-dlugie -- run /scripts/dlugie.js -e N=4 -e TTFT_MS=90000 -e TOTAL_S=30
   ```
   `scripts/pomiar.py` uruchamia k6 i co 2 s próbkuje `/diag` i atrapę; na końcu wypisuje przyrost
   odpowiedzi atrapy (`cancelled_*` = generacje porzucone). U mnie: **4 × 504 po 181.6–191.6 s**
   (3 × timeout 60 s — SDK ponawia), **10 porzuconych generacji** u atrapy.

### B. Klient rezygnuje (W16) — ~3 min przed, ~30 s po
4. **Hipoteza:** 6 analiz po 150 s generacji, ale klient (k6) rezygnuje po 20 s. Co stanie się
   z generacjami u dostawcy po rozłączeniu? Kiedy zwolnią się sloty?
   ```bash
   python scripts/pomiar.py ex10-rozlaczenie -- run /scripts/dlugie.js -e N=6 -e TOTAL_S=150 -e TTFT_MS=2000 -e K6_TIMEOUT=20s
   ```
   W trakcie patrz na `generating` atrapy. U mnie: atrapa generuje dalej „do nikogo” — sloty u dostawcy
   wolne dopiero **172.9 s** po rozłączeniu; **18 porzuconych generacji** (każda analiza 3× — po timeoucie
   60 s SDK ponawia, mimo że klienta dawno nie ma).

### C. Zawieszony dostawca, krótkie żądania (W6) — ~4.5 min przed, ~1 min po
5. **Hipoteza:** dostawca milczy 120 s na każdym streszczeniu (domyślny read SDK = 600 s). Ruch 2/s przez
   30 s. Ile slotów zajmą zawieszone wywołania? Kiedy przyjdzie ostatnia odpowiedź?
   ```bash
   for i in $(seq 60); do curl -s -o /dev/null -w '%{http_code} %{time_total}\n' -X POST -H 'x-mock-ttft-ms: 120000' 127.0.0.1:8060/claims/$i/summary & sleep 0.5; done > w6.txt
   curl -s 127.0.0.1:8060/diag | python -m json.tool | head -12      # po ~30 s: sloty, kolejka
   wait; sort -k2 -n w6.txt | tail -3
   ```
   ⟨E10-W6-PRZED⟩

### Naprawa
6. **`app/llm/klient.py`** — timeouty z SLO, nie „na zapas”:
   - krótkie: `anthropic.Timeout(connect=3, read=15, write=10, pool=5)`, `max_retries=0` (z ćw. 9);
   - długie: wywołanie **strumieniem** (`messages.stream`, zbierasz tekst, mierzysz TTFT), `read=60`
     (bezczynność — ping co 15 s ją resetuje), `max_retries=0` — powtórka 4-minutowej generacji to podwójny
     koszt; o ponowieniu decyduje aplikacja.
7. **`app/llm/wywolanie.py`** (`TODO ćw. 10`) — `z_deadlinem()`: deadline per klasa
   (`asyncio.timeout`, krótkie 30 s, długie 330 s → `bledy.Przeterminowane`) i strażnik rozłączenia
   (co 0.5 s `request.is_disconnected()` → anuluj pracę → `bledy.Anulowane`). `request` bywa `None`
   (worker kolejki, wsady).
8. Restart (`LLM_FALLBACK=0`) i powtórka A, B, C (przed A znów `PATCH … early_start/ping`).
   ⟨E10-W6-PO⟩

   U mnie:

   | Scenariusz | Przed | Po |
   |---|---|---|
   | A: 4 analizy, 90 s ciszy + 30 s | 4 × 504 po 181.6–191.6 s, 10 porzuconych generacji | **4 × 200 po 122.0 s**, 0 porzuconych |
   | B: 6 × 150 s, klient odchodzi po 20 s | sloty u dostawcy wolne po 172.9 s, 18 porzuconych | wolne po **0.7 s**, 6 anulowanych (`cancelled_generating`) |
   | C: cisza 120 s, 2/s × 30 s | 60 × 200 dopiero po 120–235 s; 32/32 sloty zajęte, 28 czeka; ostatnia po 254 s | 60 × **504** `timeout_dostawcy` po 15–25 s, ostatnia po 44.5 s |

9. Zresetuj atrapę (`curl -s -X POST 127.0.0.1:8061/admin/reset`), zostaw aplikację z `LLM_FALLBACK=0`
   i `python check.py ex10` (krótkie zawieszenie → 504 < 36 s; rozłączenie → generacja przerwana w 4 s;
   `max_retries=0` dla długich).

## Kryteria „done”
- [ ] Analiza 90 s ciszy + 30 s kończy się 200, bez porzuconych generacji.
- [ ] Rozłączenie klienta zwalnia slot u dostawcy w sekundach (`cancelled_generating` rośnie).
- [ ] Zawieszony dostawca daje krótkim szybkie 504 z przyczyną, zamiast trzymać sloty minutami.
- [ ] Umiesz narysować łańcuch: timeout k6 > deadline aplikacji > read timeout SDK (i dlaczego w tej kolejności).
- [ ] `python check.py ex10` przechodzi.

## Pytania kontrolne
1. Ustawiłeś klientowi długich `timeout=330`. Dlaczego to nie jest deadline 330 s?
2. W scenariuszu C po naprawie odpowiedzi przychodzą po 15–25 s, choć read timeout to 15 s. Skąd do 10 s więcej?
3. Dlaczego wyjątek timeoutu w trakcie strumienia trzeba łapać osobno i jak to wpływa na ponowienia z ćw. 9?

Odpowiedzi: `solutions/pytania_odpowiedzi.md`.

## ★ Bonus (opcjonalnie)
Profil `pauzy` (`curl -X POST 127.0.0.1:8061/admin/profile/pauzy`): 20 s przerwy w środku strumienia.
Przy jakim `read` wywołanie przeżywa pauzę bez pingów? Co by się stało z `read=15`?

---
Utknąłeś? `solutions/hints/ex10_hint1.md` → `hint2` → `hint3`. Gotowe rozwiązanie:
`solutions/ex10_klient.py` → `app/llm/klient.py` (zawiera ćw. 9) i `solutions/ex10_wywolanie.py` → `app/llm/wywolanie.py`.
