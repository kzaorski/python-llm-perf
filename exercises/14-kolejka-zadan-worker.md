# Ćwiczenie 14: Kolejka zadań taskiq — metryki kolejki i współbieżność workera

> Czas: ~50 min (dwa przebiegi po 200 zadań, każdy ~0.5–1 min, plus uruchomienie workera i eksportera)

> Blok V — Kolejka zadań, cache, batching, rzeczywistość (ćw. 14–18). Najpierw czytanka
> `14a-kolejki-zadan-cache-batching.md`; `00-teoria.md` „Prawo Little'a”, „Gdy dopływ przekracza pojemność”.

## Cel
W ćw. 12 długie analizy dostawały 503, bo ich pojemność (~0.1/s) była mniejsza niż dopływ. Typowa odpowiedź
architektoniczna: „przenieśmy to do kolejki zadań”. Kolejka nie dodaje pojemności — przenosi czekanie w miejsce,
w którym klient nie trzyma połączenia. Żeby nią sterować, musisz widzieć **ile czeka** i **jak długo czeka
najstarsze**, a współbieżność workera musi wynikać z mocy dostawcy, a nie z domyślnych wartości biblioteki.

## Teoria w pigułce
- **Kolejka zadań** (taskiq + Redis Streams) — aplikacja zapisuje zlecenie w strumieniu (`POST
  /claims/{n}/summary/async` → `{"zadanie": id}`), worker je odbiera i wykonuje, wynik leży w Redisie
  (`GET /jobs/{id}` → `czeka_lub_w_toku` | `gotowe` | `blad`). Intuicja: semafor z ćw. 06, tylko trwały i
  między procesami. (→ `14a`)
- **Długość kolejki ≠ `XLEN`** — taskiq nie usuwa przetworzonych wpisów ze strumienia, więc `XLEN` rośnie z każdym
  zleceniem. Kolejkę opisuje grupa konsumentów: `lag` (jeszcze nieodebrane), `pending` (odebrane, niepotwierdzone)
  i wiek najstarszego nieodebranego wpisu (ID wpisu = znacznik czasu w ms).
- **Współbieżność workera** = `--workers` × `--max-async-tasks`. Z Little'a: L = λ·W — przy mocy dostawcy 8
  generacji naraz i ~1.6 s na zadanie przepustowość ≈ 5 zadań/s; więcej równoległości daje tylko 529 (overloaded).
- **Prefetch** (`xread_count`) — ile wpisów proces pobiera „na zapas”. Pułapka: pobrane = odebrane, więc znikają
  z `lag` — kolejka wygląda na pustą, choć nic nie jest zrobione, a jeden proces może zawłaszczyć wszystko.

## Kroki
1. Stan po ćw. 13, aplikacja na 8060. W dwóch nowych terminalach (T2, T3) uruchom worker z **domyślnymi**
   ustawieniami taskiq i eksporter metryk kolejki:
   ```bash
   taskiq worker app.zadania:broker --workers 2 --max-async-tasks 100     # T2
   python -m app.kolejka_metryki                                          # T3 → http://127.0.0.1:8063/metrics
   curl -s 127.0.0.1:8063/metrics | grep -E '^kolejka_'
   ```
   Eksporter pokazuje na razie tylko `kolejka_xlen`.
2. **Hipoteza:** zlecisz 200 streszczeń w tle przy profilu atrapy `przeciazenie` (moc 8 generacji + kolejka 8 u
   dostawcy). Worker ma 2 × 100 = 200 miejsc. Ile zadań skończy się błędem? Co pokaże `XLEN` po zakończeniu?
3. Zlecenie 200 zadań i obserwacja:
   ```bash
   curl -s -X POST 127.0.0.1:8061/admin/profile/przeciazenie
   for i in $(seq 200); do curl -s -o /dev/null -X POST 127.0.0.1:8060/claims/$i/summary/async; done
   curl -s 127.0.0.1:8063/metrics | grep -E '^kolejka_'
   ID=$(curl -s -X POST 127.0.0.1:8060/claims/7/summary/async | python -c 'import json,sys; print(json.load(sys.stdin)["zadanie"])')
   curl -s 127.0.0.1:8060/jobs/$ID
   ```
   W Prometheusie (po ~10 s):
   ```
   sum by (wynik) (increase(zadania_wykonane_total[5m]))
   kolejka_xlen
   ```
   ⟨E14-PRZED⟩
4. **Metryki kolejki.** W **`app/kolejka_metryki.py`** (`TODO ćw. 14`) dodaj gauge `kolejka_lag`,
   `kolejka_pending`, `kolejka_wiek_najstarszego_s` (i opcjonalnie `kolejka_wiek_najstarszego_pending_s`):
   `XINFO GROUPS` → `lag`, `pending`, `last-delivered-id`; pierwszy wpis po `last-delivered-id` (`XRANGE`
   z wyłącznym początkiem `(`) → jego wiek. Restart eksportera (T3), `curl … | grep ^kolejka_`.
5. **Hipoteza przed powtórką:** z nowymi metrykami, przy tym samym workerze 2 × 100, ile wyniesie `kolejka_lag`
   w trakcie? Dlaczego?
6. Powtórz krok 3 (`POST /admin/reset` atrapy przed i po) i obserwuj:
   ```
   max_over_time(kolejka_lag[5m])
   max_over_time(kolejka_pending[5m])
   max_over_time(kolejka_wiek_najstarszego_s[5m])
   ```
   U mnie (2 × 100, prefetch 100): **179/200 zadań z błędem** w 6 s (220 odpowiedzi 529 u atrapy), a
   `kolejka_lag` max **0** — prefetch zabrał wszystko, kolejka „pusta”, choć prawie nic się nie udało.
7. **Współbieżność workera (W15).** W **`app/zadania.py`** ustal prefetch równy współbieżności procesu
   (`ZADANIA_MAX_ASYNC`, domyślnie 4) i uruchom worker tak, by suma = moc dostawcy przeznaczona dla zadań:
   ```bash
   taskiq worker app.zadania:broker --workers 2 --max-async-tasks 4      # T2, 2 × 4 = 8
   ```
8. Restart workera, `POST /admin/reset`, powtórka kroku 3 i zapytań z kroku 6. ⟨E14-PO⟩

   U mnie: **200/200 zadań OK** w 28.7 s, 0 × 529, `kolejka_lag` max 190 → 0 (kolejka widoczna i opróżniana ~7/s).
9. `python check.py ex14` (eksporter z `kolejka_lag` i `kolejka_wiek_najstarszego_s` na 8063; 60 zadań przy
   `przeciazenie` — wszystkie gotowe, 0 błędów). Zostaw worker i eksporter włączone do końca bloku albo zatrzymaj
   je (Ctrl+C) — kolejne ćwiczenia ich nie wymagają.

## Kryteria „done”
- [ ] Na :8063 są `kolejka_lag`, `kolejka_pending`, `kolejka_wiek_najstarszego_s`; po końcu dopływu lag wraca do 0.
- [ ] Umiesz wyjaśnić, dlaczego `XLEN` nie jest długością kolejki i dlaczego przy dużym prefetchu lag = 0.
- [ ] Współbieżność workera (`--workers` × `--max-async-tasks`) wynika z mocy dostawcy; 0 błędów 529.
- [ ] `python check.py ex14` przechodzi.

## Pytania kontrolne
1. Przy 2 × 4 wszystkie 200 zadań się udało, ale trwało to 28.7 s zamiast 6 s. Czy to gorszy wynik? Co mówi o tym Little?
2. Masz dwa workery na różnych maszynach i prefetch 100. Pierwszy wystartował 2 s wcześniej. Co zobaczysz w
   `pending` i w czasie zakończenia ostatniego zadania?
3. Na jakie wartości `kolejka_wiek_najstarszego_s` ustawiłbyś alert i dlaczego wiek, a nie długość kolejki?

Odpowiedzi: `solutions/pytania_odpowiedzi.md`.

## ★ Bonus (opcjonalnie)
Przenieś długie analizy z ćw. 12 do kolejki zadań (zlecenie + `GET /jobs/{id}`). Puść `k6/mieszany.js` i porównaj
z przebiegiem B z ćw. 12: zamiast 42 odmów 503 masz kolejkę — jaki wiek najstarszego zadania osiąga i kiedy
przestaje to być akceptowalne?

---
Utknąłeś? `solutions/hints/ex14_hint1.md` → `hint2` → `hint3`. Gotowe rozwiązanie:
`solutions/ex14_kolejka_metryki.py` → `app/kolejka_metryki.py` i `solutions/ex14_zadania.py` → `app/zadania.py`.
