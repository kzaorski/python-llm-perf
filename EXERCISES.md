# Spis ćwiczeń i czytanek — python-llm-perf

Kolejność jest progresywna — każde ćwiczenie buduje na poprzednim (stan aplikacji „po ćw. NN” możesz też
złożyć skryptem `scripts/nakladka.py --do NN`). Czytanki teoretyczne (bez zadań) poprzedzają bloki, których
dotyczą. Po każdym bloku jest mini-incydent: jedna wada, diagnoza bez czytania kodu (`./incydent.sh`).

## Mapa umiejętności

Po ukończeniu kursu umiesz:
- czytać trace żądania LLM: czekanie na slot vs obsługa vs TTFT; RED w Grafanie (ćw. 01)
- rozpoznać model zamknięty generatora i coordinated omission; dobrać executor k6 (ćw. 02)
- wyznaczyć pojemność z prawa Little'a i znaleźć kolano krzywej wykorzystanie → czekanie (ćw. 03)
- wykryć blokadę pętli zdarzeń od strony systemu: przepustowość, kolejka, p99 w ruchu otwartym (ćw. 04)
- wykryć wyczerpanie puli wątków anyio (40) — czekanie bez CPU (ćw. 05)
- wykryć za mało slotów / za małą pulę połączeń — czekanie na slot, PoolTimeout (ćw. 06)
- dobrać model procesów gunicorna (sync vs UvicornWorker) i liczbę procesów (ćw. 07)
- odczytać limity dostawcy (429, `anthropic-ratelimit-*`) i ograniczyć tempo po swojej stronie (ćw. 08)
- rozpoznać burzę ponowień (SDK × aplikacja, brak jittera) i zmierzyć amplifikację (ćw. 09)
- ustawić budżet timeoutów dla wywołań sekundowych i wielominutowych: read ≠ deadline, anulowanie po
  rozłączeniu, ping a bezczynność, timeouty k6/gunicorna (ćw. 10)
- zbudować fallback z wyłącznikiem (stany, półotwarcie) (ćw. 11)
- wprowadzić backpressure i odrzucanie nadmiaru; rozdzielić pule krótkich i wielominutowych (ćw. 12)
- mierzyć TTFT end-to-end i wykryć buforowanie strumienia, którego k6 nie widzi (ćw. 13)
- obserwować kolejkę zadań (lag, wiek najstarszego) i dobrać współbieżność workera (ćw. 14)
- wykryć cache stampede i naprawić go single-flightem (ćw. 15)
- dobrać okno i rozmiar wsadu, mierząc oba końce (ćw. 16)
- skalibrować model pojemności na prawdziwym API (ćw. 17, opcjonalnie płatne)
- zdiagnozować złożony incydent z kilkoma wadami naraz (ćw. 18)

## Ćwiczenia

| # | Plik | Czas | Co robisz |
|---|---|---|---|
| — | `exercises/00-teoria.md` | ~60 min | **Czytanka:** kolejki, prawo Little'a, kolano, model otwarty/zamknięty, RED/USE, LLM i wywołania minutowe (przeczytaj pierwsze) |
| — | `exercises/01a-teoria-kolejek-w-praktyce.md` | ~30 min | **Czytanka:** teoria kolejek w praktyce (przed blokiem I) |
| 1 | `exercises/01-pierwszy-trace.md` | ~45 min | Start stosu, pierwszy trace; span `llm.queue_wait`, czekanie w metrykach |
| 2 | `exercises/02-model-otwarty-vs-zamkniety.md` | ~40 min | k6: model otwarty vs zamknięty, coordinated omission (W14) |
| 3 | `exercises/03-prawo-littlea-pojemnosc.md` | ~45 min + ~20 | Rampa, prawo Little'a, kolano krzywej; **mini-incydent I** |
| — | `exercises/04a-asyncio-petla-i-pule.md` | ~30 min | **Czytanka:** asyncio, pętla zdarzeń i pule (przed blokiem II) |
| 4 | `exercises/04-sync-klient-w-async.md` | ~45 min | Synchroniczny klient w `async def` — skutek systemowy (W1) |
| 5 | `exercises/05-pula-watkow-anyio.md` | ~30 min | Pula wątków anyio 40 (W2) |
| 6 | `exercises/06-pula-slotow-i-polaczen.md` | ~45 min | Za mało slotów / pula połączeń, PoolTimeout (W3) |
| 7 | `exercises/07-gunicorn-model-procesow.md` | ~45 min + ~20 | gunicorn sync vs UvicornWorker (W13); **mini-incydent II** |
| — | `exercises/08a-limity-retry-timeouty.md` | ~30 min | **Czytanka:** limity, ponowienia, timeouty, fallback (przed blokiem III) |
| 8 | `exercises/08-limity-dostawcy.md` | ~45 min | 429, nagłówki limitów, limiter tempa (W4) |
| 9 | `exercises/09-burza-ponowien.md` | ~40 min | Burza ponowień, jitter, budżet (W5) |
| 10 | `exercises/10-timeouty-i-deadline.md` | ~80 min | Timeouty, deadline, anulowanie — testy wielominutowe (W6, W16, W17) |
| 11 | `exercises/11-fallback-wylacznik.md` | ~40 min + ~20 | Fallback z wyłącznikiem (W12); **mini-incydent III** |
| — | `exercises/12a-backpressure-i-streaming.md` | ~30 min | **Czytanka:** backpressure, odrzucanie, streaming (przed blokiem IV) |
| 12 | `exercises/12-backpressure-odrzucanie.md` | ~90 min | Ruch mieszany sekundy + minuty, 3-min dopływ + drain (W7, W8, W18) |
| 13 | `exercises/13-streaming-ttft.md` | ~40 min + ~20 | TTFT u klienta, buforowanie strumienia (W9); **mini-incydent IV** |
| — | `exercises/14a-kolejki-zadan-cache-batching.md` | ~25 min | **Czytanka:** kolejki zadań, cache, batching (przed blokiem V) |
| 14 | `exercises/14-kolejka-zadan-worker.md` | ~50 min | taskiq: metryki kolejki, współbieżność i prefetch workera (W15) |
| 15 | `exercises/15-cache-stampede.md` | ~30 min | Cache stampede, single-flight (W10) |
| 16 | `exercises/16-batching.md` | ~35 min | Okno i rozmiar wsadu (W11) |
| 17 | `exercises/17-atrapa-vs-claude.md` | ~30 min | Atrapa vs prawdziwy Claude (opcjonalnie, ≈ $0.005; bez klucza `--tylko-atrapa`) |
| 18 | `exercises/18-final-incydent.md` | ~90 min | **Finał:** incydent z kilkoma wadami naraz, diagnoza bez kodu, raport |

Łącznie: ćwiczenia z mini-incydentami ~16 h, czytanki ~3.5 h (czasy czytanek to szacunek lektury).
Najdłuższe ćwiczenia (10, 12, 18) zawierają prawdziwe testy wielominutowe — nie skracaj ich profilem
sekundowym, on służy tylko do szybkiego podglądu.

Pojęcia w pigułce: `slownik.md`. Rozwiązania i podpowiedzi: katalog `solutions/` (`solutions/README.md`).
Weryfikacja „done”: `python check.py exNN` (albo `python check.py --all`).
