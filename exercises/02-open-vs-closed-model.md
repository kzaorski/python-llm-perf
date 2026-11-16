# Ćwiczenie 2: k6 — model otwarty vs zamknięty (coordinated omission)

> Czas: ~40 min (dwa przebiegi k6 po 60 s + analiza)

> Blok I. Teoria: `00-teoria.md` „Model otwarty vs zamknięty i coordinated omission”, „Percentyle i ogon”;
> czytanka `01a-teoria-kolejek-w-praktyce.md`.

## Cel
Puszczasz ten sam ruch dwoma generatorami: zamkniętym (stała liczba wirtualnych użytkowników,
każdy czeka na odpowiedź) i otwartym (żądania w stałym tempie, niezależnie od odpowiedzi).
Zobaczysz, że raport modelu zamkniętego jest „ładny”, bo generator sam zwalnia, gdy system zwalnia —
i nie widzi kolejki. Uzupełniasz scenariusz otwarty w `k6/otwarty.js`.

## Teoria w pigułce
- **Model zamknięty** (`constant-vus`) — N użytkowników w pętli „wyślij → czekaj → (pauza) → wyślij”.
  Tempo NIE jest parametrem: wynosi N / (czas odpowiedzi + pauza). Gdy system zwalnia, generator
  wysyła mniej. Po co: modeluje stałą pulę klientów (np. N workerów batchowych). Pułapka: „4 VU” to nie
  „4 żądania/s”.
- **Model otwarty** (`constant-arrival-rate`, `ramping-arrival-rate`) — żądania przychodzą w zadanym
  tempie λ, tak jak klienci z internetu, którzy nie wiedzą o Twojej kolejce. Po co: tylko ten model
  pokazuje kolejkę i prawdziwy ogon. Pułapka: k6 potrzebuje wystarczającej puli VU — gdy jej zabraknie,
  sam „zamyka” model i gubi iteracje (`dropped_iterations` > 0).
- **Coordinated omission** — generator, który czeka na odpowiedź, „umawia się” z systemem: w chwilach
  przestoju nie wysyła żądań, więc nie mierzy ich (nieistniejącego) czekania. Raport zaniża ogon
  dokładnie tam, gdzie boli najbardziej. (→ `00-teoria.md`; `slownik.md`)
- **Osiągnięte tempo** — zawsze podawaj obok percentyli, ile żądań/s naprawdę wysłano. Porównanie
  p99 dwóch testów ma sens tylko przy tej samej intensywności.

## Kroki
1. Stan po ćw. 1: aplikacja na 8060 (`uvicorn app.main:app --port 8060`), 4 sloty LLM.
   Streszczenie trwa ~1 s, więc pojemność ≈ 4 / 1.05 s ≈ 3.8 żądania/s.
2. **Model zamknięty**, 4 VU bez pauzy, 60 s (terminal T2):
   ```bash
   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/zamkniety.js -e VUS=4 -e PAUZA_S=0 -e CZAS=60s
   ```
   Podsumowanie trafia też do `wyniki/ex02-zamkniety.json`. Zanotuj: `http_reqs` (tempo/s),
   `http_req_duration` p99, `app_czekanie_krotkie` p99.
3. **Zanim uruchomisz model otwarty:** ten sam system, nominalnie ta sama intensywność (4 żądania/s).
   Czy p99 będzie podobne? Co pokaże `app_czekanie_krotkie`?
4. Otwórz **`k6/otwarty.js`** i uzupełnij `options.scenarios` (TODO ćw. 02): executor modelu otwartego
   o stałym tempie `RATE` żądań/s przez `CZAS`, z pulą VU dobraną tak, by `dropped_iterations` było 0.
5. **Model otwarty**, 4/s, 60 s:
   ```bash
   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/otwarty.js -e RATE=4 -e CZAS=60s
   ```
   U mnie (stan po ćw. 1):

   | Model | Osiągnięte tempo | p50 / p99 | czekanie p99 | dropped |
   |---|---|---|---|---|
   | zamknięty, 4 VU bez pauzy | 3.75/s | 1.04 / **1.57 s** | 0 | 0 |
   | otwarty, 4/s | 3.52/s (dopływ 4/s > pojemność ~3.8/s) | 2.99 / **4.41 s** | 3.28 s | 0 |

   Zamknięty nie widzi kolejki (czekanie 0 — każdy VU czeka na swoją odpowiedź, więc nigdy nie ma
   więcej niż 4 żądań naraz). Otwarty przy tej samej nominalnej intensywności pokazuje kolejkę na semaforze.
6. Pułapka „VU = żądania/s”: powtórz model zamknięty z pauzą 1 s:
   ```bash
   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/zamkniety.js -e VUS=4 -e PAUZA_S=1 -e CZAS=40s
   ```
   U mnie tempo spadło do **1.92/s** — model sam zwolnił do połowy, a raport nadal wygląda „zdrowo”
   (p99 1.63 s). Ten przebieg nadpisał `wyniki/ex02-zamkniety.json` — do checka wystarczy dowolny
   z dwóch przebiegów zamkniętych.
7. Prometheus (k6 wysyła metryki przez remote write, tag `model`):
   ```
   max by (model) (k6_http_req_duration_p99)
   max by (model) (k6_app_czekanie_krotkie_p99)
   sum by (model) (k6_dropped_iterations_total)
   ```
8. `python check.py ex02`

## Kryteria „done”
- [ ] `k6/otwarty.js` ma scenariusz `constant-arrival-rate`; przebieg 4/s ma `dropped_iterations` = 0.
- [ ] Umiesz wskazać w wynikach, dlaczego p99 zamkniętego jest niższe, choć system jest ten sam.
- [ ] Przy każdym porównaniu podajesz osiągnięte tempo, nie liczbę VU.
- [ ] `python check.py ex02` przechodzi (p99 otwartego > 1.3 × zamkniętego, 0 zgubionych iteracji).

## Pytania kontrolne
1. Dlaczego w modelu zamkniętym z 4 VU czekanie na semafor wynosi 0, skoro aplikacja ma 4 sloty?
2. Co oznacza `dropped_iterations` > 0 w modelu otwartym i dlaczego unieważnia wynik?
3. Kiedy model zamknięty JEST właściwy? Podaj przykład z tej aplikacji.

Odpowiedzi: `solutions/pytania_odpowiedzi.md`.

## ★ Bonus (opcjonalnie)
Ustaw w `k6/otwarty.js` celowo za mało VU (`preAllocatedVUs: 2, maxVUs: 4`) i puść 4/s. Ile iteracji
zgubił k6 i jak zmienił się p99? To ten sam błąd co model zamknięty, tylko ukryty w konfiguracji.

---
Utknąłeś? `solutions/hints/ex02_hint1.md` → `hint2` → `hint3`. Gotowe rozwiązanie:
`solutions/ex02_otwarty.js` → `k6/otwarty.js`.
