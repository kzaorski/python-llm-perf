# Ćwiczenie 12: Backpressure i odrzucanie nadmiaru — ruch mieszany: sekundy i minuty w jednej aplikacji

> Czas: ~90 min, w tym 2–3 testy wielominutowe po 6.5–10 min (180 s dopływu + opróżnianie)

> Blok IV — Backpressure i streaming (ćw. 12–13). Najpierw czytanka `12a-backpressure-i-streaming.md`;
> `00-teoria.md` „Gdy dopływ przekracza pojemność”, „Wywołania wielominutowe”.

## Cel
Do krótkich streszczeń (sekunda) dochodzą analizy dokumentacji (1–4 min). Puszczasz realistyczny ruch
mieszany w modelu otwartym przez 3 minuty i patrzysz, co dzieje się w trakcie i PO końcu dopływu:
krótkie czekają minutami za długimi (head-of-line blocking we wspólnej puli), kolejka długich rośnie
bez limitu, klienci rezygnują, a dostawca generuje „do nikogo”. Naprawiasz to trzema mechanizmami:
osobne pule per klasa, limit kolejki, budżet czekania (szybkie 503 z `Retry-After`).

## Teoria w pigułce
- **Head-of-line blocking** — wspólna kolejka/pula dla zadań o skrajnie różnym czasie obsługi: kilka
  długich zajmuje sloty na minuty, a krótkie (które same trwałyby sekundę) czekają za nimi. Mediana
  krótkich ≫ ich czas obsługi. Naprawa: osobne pule (bulkhead) — każda klasa ma własny limit; suma ≤ moc dostawcy.
- **Backpressure** — system mówi „nie teraz” zamiast przyjmować wszystko. Kolejka bez limitu nie jest
  buforem, tylko obietnicą bez pokrycia: przy dopływie > pojemność rośnie bez końca, a wiek
  najstarszego żądania przekracza cierpliwość klienta. (→ `12a`)
- **Odrzucanie nadmiaru (load shedding)** — dwa progi: limit długości kolejki (odrzuć od razu) i budżet
  czekania (kto nie dostał slotu w X s, dostaje 503). Szybkie 503 z `Retry-After` w milisekundach jest
  lepsze niż 200 po 5 minutach, na które nikt już nie czeka. Pułapka: odrzucenia wyglądają w RED jak
  błędy — ale to poprawna odpowiedź przeciążonego systemu; mierz je osobno (`wynik="odrzucone"`).
- **Zaległość i drain** — po końcu dopływu system jeszcze pracuje. Ile czekało w chwili końca dopływu
  i ile trwało opróżnianie — to wprost mówi, jak długo klienci po szczycie dostają stare odpowiedzi.
- **Pojemność długich** — 16 slotów przy ~150 s na analizę ≈ 0.1 analizy/s. Dopływ 0.4/s jej nie
  zmieści NIGDY — odrzucanie jest tu poprawne, a docelowo długie trafiają do kolejki zadań (ćw. 14).

## Kroki
1. Stan po ćw. 11, aplikacja na 8060 (uruchomiona normalnie). Zajrzyj do **`k6/mieszany.js`**: krótkie
   `/summary` 4/s, długie `/analysis` 0.4/s z czasem generacji U[60, 240] s (deterministyczny harmonogram,
   ziarno), timeout k6 400 s, `gracefulStop` 420 s — k6 NIE zrywa żądań w toku po końcu dopływu (domyślne
   30 s zafałszowałoby zaległość i drain).
2. **Hipoteza (zapisz liczby):** wspólna pula 32 slotów, długie trafiają średnio 24 na minutę ×
   ~150 s. Po ilu sekundach długie zajmą wszystkie sloty? Ile będzie czekać krótkie streszczenie w t = 180 s?
   Ile potrwa opróżnianie po końcu dopływu?
3. **Przebieg A (przed naprawą), ~9 min:**
   ```bash
   python scripts/pomiar.py ex12-mieszany --dopływ-s 180 -- run -q -o experimental-prometheus-rw /scripts/mieszany.js -e CZAS=180s
   ```
   W trakcie obserwuj (Prometheus, „Last 15 minutes”):
   ```
   max by (klasa) (llm_waiting)
   max by (klasa) (llm_oldest_waiting_age_seconds)
   max by (klasa) (llm_inflight)
   sum by (klasa, wynik) (increase(app_requests_total[5m]))
   ```
   Zwróć uwagę na chwilę, gdy `llm_inflight{klasa="dlugie"}` dochodzi do 32 — od niej krótkie stoją.
   Po zakończeniu: `wyniki/ex12-mieszany.json` (k6: czasy per klasa z `Server-Timing`) i
   `wyniki/ex12-mieszany-przebieg.json` (`zaleglosc_na_koniec_doplywu`, `drain_po_koncu_doplywu_s`,
   przyrost odpowiedzi atrapy — `cancelled_*` to generacje porzucone).
4. **Osobne pule (W18).** W **`app/llm/limiter.py`** zamień jeden semafor na słownik per klasa:
   krótkie `SLOTY` (32), długie `LLM_SLOTY_DLUGIE` (16; z Little'a dla długich + suma ≤ moc dostawcy 64).
   `semafor(klasa)` zwraca semafor klasy.
5. **(Zalecany) Przebieg C — tylko osobne pule, ~10 min.** Restart, polecenie z kroku 3. Czy krótkie są
   już zdrowe? Co dzieje się z długimi i z ich kolejką? (Jeśli brakuje czasu, pomiń — liczby są w tabeli.)
6. **Backpressure (W7, W8).** W **`app/przeciazenie.py`** (`TODO ćw. 12`):
   - `dopusc(klasa)`: gdy w kolejce klasy czeka już `MAX_CZEKAJACYCH[klasa]` (krótkie 64, długie 8) —
     `raise Odrzucone("kolejka_pelna", retry_after=…)` (aplikacja zamienia to na 503 + `Retry-After`);
   - `max_czekania(klasa)`: budżet czekania na slot — krótkie 5 s, długie 20 s (`limiter.slot` rzuca
     `Odrzucone` po jego przekroczeniu).
7. **Przebieg B (po naprawie), ~6.5 min:** restart i polecenie z kroku 3.

   U mnie (794 żądania: 721 krótkich, 73 długie; `dropped_iterations` = 0 we wszystkich):

   | Wariant | Krótkie: czekanie p50 / p99 | Krótkie: całość p99 | Długie: wynik | Długie: czekanie p50 / p99 | Zaległość w t = 180 s | Drain |
   |---|---|---|---|---|---|---|
   | A — wspólna pula, kolejka bez limitu | **29.0 / 131.2 s** | 132.3 s | 72 OK (1 zerwane) | 32.2 / 130.9 s | krótkie: **287 czeka**, najstarsze 71.6 s; długie: 31 w toku + 28 czeka | **342 s** |
   | C — osobne pule, bez limitu/budżetu | 0.0 / 0.0 s | 1.74 s | 43 OK, **30 porzuconych przez klienta** (400 s) → 30 generacji anulowanych | **88.0 / 271.8 s** | długie: 16 w toku + **46 czeka**, najstarsze 114.6 s | 402 s |
   | B — osobne pule + limit kolejki + budżet | 0.0 / 0.0 s | 1.76 s | 30 OK, **42 × 503 szybko** | 0.0 / 19.4 s | długie: 16 w toku + 8 czeka (17 s) | **213 s** |

   A → C: osobne pule usuwają head-of-line blocking. C → B: limit i budżet zamieniają 30 porzuceń po
   minutach (praca zmarnowana) w 42 szybkie odmowy z `Retry-After`; drain 402 → 213 s.
8. **Szybki podgląd (opcjonalnie, NIE zastępuje przebiegu minutowego):** ten sam kształt ruchu
   w krótszej skali — przydatny, gdy chcesz tylko sprawdzić, że kod działa:
   ```bash
   python scripts/pomiar.py ex12-podglad --dopływ-s 60 -- run -q /scripts/mieszany.js -e CZAS=60s -e DLUGIE_OD_S=20 -e DLUGIE_DO_S=60
   ```
   ⟨E12-PODGLAD⟩
9. `python check.py ex12` (30 długich po 15 s + 20 krótkich: krótkie czekają < 1 s, nadmiar długich
   dostaje szybkie 503; jeśli jest `wyniki/ex12-mieszany.json`, check dopisze czekanie krótkich z Twojego przebiegu).

## Kryteria „done”
- [ ] W przebiegu mieszanym krótkie nie czekają na slot (p99 ≈ 0), niezależnie od długich.
- [ ] Nadmiar długich dostaje szybkie 503 z `Retry-After`, a nie odpowiedź po minutach; kolejka ma limit.
- [ ] Z raportu `*-przebieg.json` umiesz odczytać zaległość w chwili końca dopływu i czas opróżniania.
- [ ] `python check.py ex12` przechodzi.

## Pytania kontrolne
1. Po naprawie część klientów dostaje 503. Dlaczego to lepszy wynik niż 200 dla wszystkich po 5 minutach?
2. Jak dobrać budżet czekania krótkich (5 s)? Co wiesz o kliencie, czego nie wie aplikacja?
3. Pojemność długich (~0.1/s) < dopływ (0.4/s). Jakie masz opcje oprócz odrzucania? Co wybierzesz w ćw. 14?

Odpowiedzi: `solutions/pytania_odpowiedzi.md`.

## ★ Bonus (opcjonalnie)
Dodaj priorytet: krótkie mogą „pożyczyć” wolne sloty puli długich, gdy ta jest pusta, ale nigdy
odwrotnie. Zmierz przebieg B z tą zmianą — co dzieje się z drainem?

---
Utknąłeś? `solutions/hints/ex12_hint1.md` → `hint2` → `hint3`. Gotowe rozwiązanie:
`solutions/ex12_limiter.py` → `app/llm/limiter.py` (zawiera ćw. 1, 6, 8) i
`solutions/ex12_przeciazenie.py` → `app/przeciazenie.py`.
