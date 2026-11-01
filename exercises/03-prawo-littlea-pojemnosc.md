# Ćwiczenie 3: Prawo Little'a i kolano krzywej — ile slotów potrzeba?

> Czas: ~45 min (dwie rampy po ~2.5 min + obliczenia) + mini-incydent I ~20 min

> Blok I. Teoria: `00-teoria.md` „Prawo Little'a”, „Wykorzystanie i czas oczekiwania: kolano krzywej”,
> „Gdy dopływ przekracza pojemność”; czytanka `01a-teoria-kolejek-w-praktyce.md`.

## Cel
Wyznaczasz pojemność aplikacji dwiema drogami — rachunkiem (prawo Little'a) i pomiarem (rampa tempa
w modelu otwartym) — i sprawdzasz, że się zgadzają. Znajdujesz „kolano”: tempo, od którego czekanie
rośnie szybciej niż przepustowość. Kodu nie zmieniasz; zmieniasz tylko liczbę slotów zmienną `LLM_SLOTY`.

## Teoria w pigułce
- **Prawo Little'a: L = λ · W** — średnia liczba żądań w systemie (L) = tempo napływu (λ) × średni czas
  w systemie (W). Działa dla dowolnej stabilnej kolejki, bez założeń o rozkładach. Po co: z λ i czasu
  wywołania LLM liczysz, ile wywołań będzie w toku — czyli ile slotów potrzebujesz. Pułapka: W to czas
  OBSŁUGI, jeśli liczysz sloty (czekanie nie zajmuje slotu); i to średnia — na ogon potrzebny zapas.
- **Pojemność (przepustowość maksymalna)** = sloty / czas obsługi. Przy 4 slotach i ~1.05 s:
  ≈ 3.8 żądania/s. Powyżej tego kolejka rośnie bez końca (dopływ > odpływ).
- **Wykorzystanie (ρ) i kolano** — ρ = λ / pojemność. Czas oczekiwania rośnie nieliniowo z ρ (dla
  prostego modelu ~ ρ/(1−ρ)): przy 50% prawie zero, przy 90% kilka czasów obsługi, przy 100% bez
  granic. Kolano to miejsce na krzywej tempo → czekanie, gdzie zaczyna się ten wzrost. Po co: planujesz
  pracę PONIŻEJ kolana. Pułapka: średnie wykorzystanie 70% w oknie 5 min ukrywa minuty powyżej 100%.
- **Saturacja** — zasób (tu: sloty) zajęty w 100%: `llm_inflight` przyklejone do liczby slotów.
  To „S” z USE. (→ `00-teoria.md` „RED i USE dla tej aplikacji”)

## Kroki
1. **Rachunek najpierw.** Streszczenie u atrapy trwa ~1.05 s (p50 obsługi LLM z ćw. 1–2). Ile żądań/s
   obsłużą 4 sloty? Ile slotów trzeba na 20/s? Ile na 30/s? Zapisz liczby.
2. **Hipoteza:** rampa od 1 do 6 żądań/s co 1/s, po 20 s na schodek. Na którym schodku zacznie rosnąć
   czekanie? Ile wyniesie wtedy `llm_inflight{klasa="krotkie"}`?
3. Rampa na 4 slotach (aplikacja po ćw. 2, uruchomiona jak zwykle):
   ```bash
   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/rampa.js -e OD=1 -e DO=6 -e SKOK=1 -e KROK_S=20
   ```
   Trwa ~2.5 min. W trakcie obserwuj w Grafanie (Explore → Prometheus, zakres „Last 5 minutes”,
   tryb „Range”):
   ```
   sum(rate(app_requests_total{endpoint="summary"}[20s]))
   max(llm_inflight{klasa="krotkie"})
   histogram_quantile(0.9, sum by (le) (rate(llm_queue_wait_seconds_bucket{klasa="krotkie"}[20s])))
   ```
   U mnie (456 żądań; wartości co 20 s z Prometheusa, `query_range`):

   | t [s] | 20 | 40 | 60 | 80 | 100 | 120 | 140 | 160 |
   |---|---|---|---|---|---|---|---|---|
   | osiągnięte tempo [/s] | 0.9 | 1.9 | 2.2 | 3.4 | 3.6 | 3.6 | 4.0 | 2.9* |
   | `llm_inflight` max | 2 | 3 | **4** | 4 | 4 | 4 | 4 | 4 |
   | czekanie p90 [s] | 0 | 0 | 0 | 0.85 | 2.7 | 7.3 | 14.4 | 19.7 |

   \* po końcu dopływu (opróżnianie). Tempo zatrzymuje się na ~3.6–4/s, sloty przyklejone do 4, a czekanie
   rośnie z każdym schodkiem — k6 na koniec: czekanie p99 19.6 s przy obsłudze LLM ~1 s.
4. **Zmiana pojemności bez zmiany kodu.** Zatrzymaj aplikację i uruchom ją z liczbą slotów, którą
   policzyłeś dla ~30/s (ja wziąłem 32):
   ```bash
   LLM_SLOTY=32 uvicorn app.main:app --port 8060
   ```
5. **Hipoteza:** gdzie wypadnie kolano przy 32 slotach? (32 / 1.06 s ≈ ?)
6. Druga rampa, od 4 do 44 żądań/s co 8, po 20 s:
   ```bash
   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/rampa.js -e OD=4 -e DO=44 -e SKOK=8 -e KROK_S=20
   ```
   U mnie (okna ~22 s z Prometheusa):

   | Schodek [żądań/s] | 4 | 12 | 20 | 28 | 36 | 44 |
   |---|---|---|---|---|---|---|
   | osiągnięte tempo [/s] | 8* | 15 | 20.5 | 29.2 | 29.8 | 30.2 |
   | `llm_inflight` max | 13 | 24 | 31 | **32** | 32 | 32 |
   | czekanie p90 [s] | 0 | 0 | 0 | 1.6 | 6.1 | 9.7 |

   \* okna rate nakładają się na przejścia między schodkami — czytaj trend, nie pojedynczą komórkę.
   Kolano ≈ 28–30/s = 32 sloty / 1.06 s (Little). Powyżej tempo stoi w miejscu, a czekanie rośnie
   z każdym schodkiem — to nadmiar, który czeka w kolejce. Całość: 2997 żądań, czekanie p99 9.6 s.
7. **Uwaga o generatorze.** Przy 36–44/s k6 zgłosił u mnie `dropped_iterations` 130 i 45 błędów
   `dial: i/o timeout` (status 0). To k6 w kontenerze Docker Desktop, który nie nadąża z nowymi
   połączeniami do `host.docker.internal`, a nie odpowiedzi aplikacji (aplikacja nie zarejestrowała tych
   żądań — sprawdź `app_requests_total`). W raporcie podawaj je osobno. Powyżej kolana i tak nie
   planujesz pracy.
8. Wróć do zwykłego uruchomienia aplikacji (bez `LLM_SLOTY`) — zmianę domyślnej liczby slotów w kodzie
   zrobisz w ćw. 6.
9. `python check.py ex03` (sprawdza, że jest zapis rampy `wyniki/ex03-rampa.json` z ≥ 200 żądaniami).

## Kryteria „done”
- [ ] Liczba slotów policzona z Little'a zgadza się z kolanem zmierzonym rampą (±15%).
- [ ] Umiesz wskazać na wykresie: saturację (`llm_inflight` = sloty), początek kolejki, płaskie tempo.
- [ ] Rozumiesz, dlaczego zwiększenie slotów przesunęło kolano, ale go nie usunęło.
- [ ] `python check.py ex03` przechodzi.

## Pytania kontrolne
1. Aplikacja ma 32 sloty, wywołanie trwa 1.06 s. Napływ 40/s przez minutę. Ile żądań czeka po minucie
   i ile czeka ostatnie z nich?
2. Dlaczego do liczenia slotów bierzesz czas obsługi LLM, a nie czas odpowiedzi z k6?
3. Wywołanie LLM wydłuży się z 1 s do 3 s (dłuższe odpowiedzi). Co stanie się z kolanem? A z kosztem
   pamięci/połączeń, jeśli zwiększysz sloty 3×?

Odpowiedzi: `solutions/pytania_odpowiedzi.md`.

## ★ Bonus (opcjonalnie)
Narysuj w Grafanie panel „czekanie p90 vs wykorzystanie” (`max(llm_inflight{klasa="krotkie"}) / 32` na
osi X — w Explore wystarczą dwa zapytania na jednym wykresie). Porównaj kształt z krzywą ρ/(1−ρ).

---

## Mini-incydent I (po bloku I) — „raport z testu mówi OK, klienci mówią co innego”

> ~20 min. Diagnozujesz WYŁĄCZNIE przez k6, Grafanę i `/diag` — nie czytaj kodu w `.run/incydent-*`.

Zespół testów przysłał raport: „4 VU, 30 s, p99 1.6 s, 0 błędów — wydajność OK”. Po wdrożeniu
przy ~4 zgłoszeniach/s klienci skarżą się na odpowiedzi po 3 s i dłużej.

1. Zatrzymaj własną aplikację (port 8060 musi być wolny) i uruchom incydent:
   ```bash
   ./incydent.sh start mini-I
   ```
2. Odtwórz raport zespołu i to, co widzą klienci:
   ```bash
   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/zamkniety.js -e VUS=4 -e PAUZA_S=0 -e CZAS=30s
   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/otwarty.js -e RATE=4 -e CZAS=30s
   ```
   U mnie: zamknięty 3.69/s, p99 **1.61 s**, czekanie 0; otwarty 121 żądań w 30 s (k6 liczy tempo z opróżnianiem:
   2.63/s), p99 **2.58 s**, czekanie p99 1.46 s; `check.py ex06`: czekanie na slot p50 21.3 s / p99 42.7 s przy LLM 1.07 s.
3. Odpowiedz na podstawie metryk (bez kodu): gdzie żądania tracą czas? Który zasób jest nasycony
   i jak to widać (`llm_inflight`, `llm_queue_wait_seconds`, `mock_llm_generating`)? Dlaczego raport
   zespołu tego nie pokazał? Ile slotów potrzeba na 4/s z zapasem, a ile na docelowe 20/s?
4. Sprawdzenie: `python check.py ex06` (sonda ćw. 6 — ruch otwarty 20/s) — na incydencie FAIL z liczbami.
5. `./incydent.sh stop`, potem znów uruchom własną aplikację.

Odpowiedź (objaw → ślad → przyczyna → naprawa): `solutions/pytania_odpowiedzi.md`, sekcja „Mini-incydenty”.

---
Utknąłeś? `solutions/hints/ex03_hint1.md` → `hint2` → `hint3`. W tym ćwiczeniu nie ma kodu do skopiowania —
podpowiedzi prowadzą przez rachunek.
