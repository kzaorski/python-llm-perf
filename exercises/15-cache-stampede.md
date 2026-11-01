# Ćwiczenie 15: Cache odpowiedzi i cache stampede — 50 pytań, 50 wywołań

> Czas: ~30 min

> Blok V. Czytanka `14a-kolejki-zadan-cache-batching.md` (cache, TTL, stampede, single-flight).

## Cel
Klienci zadają w kółko te same pytania („ile trwa likwidacja szkody”). Endpoint `GET /faq?q=…` trzyma
odpowiedzi w Redisie z TTL — a mimo to przy popularnym pytaniu dostawca dostaje falę identycznych wywołań
za każdym razem, gdy klucz wygaśnie. Mierzysz stampede liczbą wywołań LLM i naprawiasz go single-flightem.

## Teoria w pigułce
- **Cache-aside z TTL** — sprawdź cache; przy chybieniu policz i zapisz. Intuicja: działa świetnie przy ruchu
  rozłożonym w czasie. Po co: wywołanie LLM kosztuje sekundy i pieniądze, odczyt z Redisa — milisekundy.
- **Cache stampede (thundering herd)** — gdy klucza nie ma (pierwszy raz albo po wygaśnięciu), każde z N
  równoczesnych żądań widzi „miss” i samo woła LLM. Przy wywołaniu trwającym sekundę i 5 pytaniach/s okno
  chybień ma szerokość czasu wywołania — a im dłużej czeka się na slot, tym szersze okno (finał, ćw. 18).
- **Single-flight** — jedno wywołanie na klucz, pozostali czekają na jego wynik. W procesie: słownik
  klucz → `asyncio.Future`; między procesami (kilka workerów gunicorna): blokada `SET klucz:blokada NX PX`
  w Redisie, reszta odpytuje cache. Pułapka: blokada bez czasu wygaśnięcia albo `Future` bez obsługi wyjątku —
  padnięcie „właściciela” zawiesza wszystkich czekających.

## Kroki
1. Stan po ćw. 14, aplikacja na 8060. Jedno pytanie dwa razy:
   ```bash
   curl -s "127.0.0.1:8060/faq?q=ile-trwa-likwidacja" | head -c 150; echo
   curl -s "127.0.0.1:8060/faq?q=ile-trwa-likwidacja" | head -c 150; echo
   ```
   Pole `cache`: `miss`, potem `hit`.
2. **Hipoteza:** 50 klientów pyta jednocześnie o to samo NOWE pytanie. Ile wywołań LLM zobaczy atrapa?
3. Pomiar — liczba odpowiedzi 200 atrapy przed i po (oba „dostawcy”, bo po ćw. 11 ruch może iść do `b`):
   ```bash
   Q="czy-polisa-obejmuje-zalanie-$RANDOM"
   A0=$(curl -s 127.0.0.1:8061/admin/stats | python -c 'import json,sys; d=json.load(sys.stdin); print(d["a"]["responses"].get("200",0)+d["b"]["responses"].get("200",0))')
   seq 50 | xargs -P 50 -I{} curl -s -o /dev/null -w '%{http_code}\n' "127.0.0.1:8060/faq?q=$Q" | sort | uniq -c
   A1=$(curl -s 127.0.0.1:8061/admin/stats | python -c 'import json,sys; d=json.load(sys.stdin); print(d["a"]["responses"].get("200",0)+d["b"]["responses"].get("200",0))')
   echo "wywołań LLM: $((A1 - A0))"
   ```
   Prometheus: `sum by (wynik) (app_cache_total)` — licznik od startu procesu (po świeżym restarcie
   `increase()` nie policzy pierwszej serii próbek, więc tu patrz na wartości). U mnie: atrapa — **50 wywołań
   LLM**, 50 × 200 dla klientów; `app_cache_total{wynik="miss"}` = 50.
4. W Tempo znajdź kilka śladów `GET /faq` z tego samego momentu: każdy ma własny `llm.call`?
5. **Single-flight (W10).** W **`app/cache.py`** (`TODO ćw. 15`) w `pobierz_albo_policz()`:
   - po chybieniu sprawdź słownik `_w_toku[k]`; jeśli jest — `await asyncio.shield(fut)` i zwróć `"wspolne"`;
   - w przeciwnym razie utwórz `Future`, wstaw do słownika, zdobądź blokadę `r.set(k + ":blokada", "1", nx=True,
     px=…)`, policz, zapisz, ustaw wynik `Future` (albo wyjątek), w `finally` usuń wpis i blokadę;
   - kto nie zdobył blokady (inny proces liczy) — odpytuje cache co ~50 ms.
6. Restart, powtórka kroku 3 z nowym `Q`. U mnie: 50 × 200, **1 wywołanie LLM**; `app_cache_total`:
   `miss` 1, `wspolne` 49.

   U mnie: **50 wywołań LLM** (p99 4.6 s) → **1 wywołanie** (49 „wspólne”), p99 1.32 s.
7. `python check.py ex15`

## Kryteria „done”
- [ ] 50 równoczesnych identycznych pytań → 1 wywołanie LLM; `app_cache_total{wynik="wspolne"}` rośnie.
- [ ] Błąd wywołania „właściciela” nie zawiesza czekających (dostają ten sam błąd, nie czekają w nieskończoność).
- [ ] `python check.py ex15` przechodzi.

## Pytania kontrolne
1. Po naprawie p99 spadło z 4.6 s do 1.32 s, choć liczba klientów ta sama. Skąd zysk po stronie latencji?
2. Dlaczego sam słownik `Future` nie wystarczy przy gunicornie z dwoma procesami (ćw. 07)?
3. Jak zachowa się single-flight, gdy wywołanie „właściciela” trwa dłużej niż TTL blokady w Redisie?

Odpowiedzi: `solutions/pytania_odpowiedzi.md`.

## ★ Bonus (opcjonalnie)
Dodaj odświeżanie z wyprzedzeniem (stale-while-revalidate): na ostatnie 10% TTL zwracaj starą wartość, a
w tle przelicz jedną kopię. Jak zmienia to wykres `rate(llm_call_duration_seconds_count[1m])` przy stałym ruchu FAQ?

---
Utknąłeś? `solutions/hints/ex15_hint1.md` → `hint2` → `hint3`. Gotowe rozwiązanie:
`solutions/ex15_cache.py` → `app/cache.py`.
