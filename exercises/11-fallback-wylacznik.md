# Ćwiczenie 11: Zapasowy dostawca z wyłącznikiem (circuit breaker)

> Czas: ~40 min (dwa przebiegi po 40 s + opróżnianie) + mini-incydent III ~20 min

> Blok III. Czytanka `08a-limity-retry-timeouty.md` (fallback, wyłącznik, stany zamknięty/otwarty/półotwarty).

## Cel
Aplikacja ma zapasowego dostawcę `b` (w atrapie: osobne limity i moc, ścieżka `/b/v1/messages`).
Gdy `a` zawiśnie, KAŻDE żądanie najpierw płaci pełny timeout u `a`, a dopiero potem idzie do `b`.
Mierzysz ten koszt pod obciążeniem i dopisujesz wyłącznik: po kilku awariach przestajemy pytać `a`
na jakiś czas, potem sprawdzamy go pojedynczą próbką.

## Teoria w pigułce
- **Fallback bez pamięci** — „spróbuj `a`, jak się nie uda, to `b`”. Przy trwałej awarii `a` czas
  każdego żądania = timeout `a` + czas `b`, a sloty są zajęte przez czekanie na `a`. Pułapka: w metrykach
  sukcesów wszystko „działa”, tylko p50 skacze o timeout.
- **Wyłącznik (circuit breaker)** — trzy stany: **zamknięty** (ruch do `a`, liczymy kolejne awarie) →
  po N awariach **otwarty** (przez T sekund od razu `b`, `a` dostaje czas na podniesienie się) → po T
  **półotwarty** (jedna próbka do `a`; sukces zamyka, porażka znów otwiera). Po co: awaria kosztuje N
  timeoutów, a nie wszystkie. Pułapka: żądania, które już czekają na `a`, i tak zapłacą timeout.
- **Co jest awarią?** Zawieszenie, błąd połączenia, 5xx — tak. **429 i 529 — nie**: to „za dużo ruchu”,
  a przerzucenie go na `b` przenosi burzę na zapasowego dostawcę. `APITimeoutError` jest podklasą
  `APIConnectionError` (łapie ją `except APIConnectionError`), a `OverloadedError` (529) nie jest
  podklasą `InternalServerError`.
- **Widoczność stanu** — stan wyłącznika jako atrybut spanu (`llm.cb.stan`) i licznik przejść w `/diag`.
  Bez tego „dlaczego ruch idzie do b?” to zagadka.

## Kroki
1. Stan po ćw. 10, aplikacja na 8060 uruchomiona **normalnie** (fallback włączony, `LLM_FALLBACK=1`
   domyślnie). Klient krótkich ma po ćw. 10 `read=15 s`.
2. Awaria `a`: dostawca milczy 30 s przed pierwszym tokenem (dłużej niż nasz read timeout):
   ```bash
   curl -s -X PATCH '127.0.0.1:8061/admin/config?provider=a' -H 'content-type: application/json' \
     -d '{"ttft_median_ms": 30000, "ttft_sigma": 0}'
   ```
3. **Hipoteza:** ruch 2/s przez 40 s. Ile wyniesie mediana czasu odpowiedzi? Ile z 80 żądań trafi do `a`?
   ```bash
   docker compose run --rm -e WYNIK=ex11-przed k6 run -o experimental-prometheus-rw /scripts/otwarty.js -e RATE=2 -e CZAS=40s
   curl -s 127.0.0.1:8061/admin/stats | python -m json.tool | head -30
   ```
   ⟨E11-PRZED⟩ Prometheus: `sum by (provider) (increase(mock_llm_requests_total[2m]))`.
4. Otwórz **`app/llm/fallback.py`** (`TODO ćw. 11`). Dopisz klasę wyłącznika (stan, licznik kolejnych
   awarii, czas otwarcia, flaga „próbka w toku”) i użyj jej w `wywolaj()`: pytaj `a` tylko, gdy
   wyłącznik pozwala; sukces → zamknij; awaria (`_awaria(e)`) → policz; inny błąd → przepuść dalej.
   Ustaw atrybut `llm.cb.stan` na bieżącym spanie i zapisuj przejścia stanów do `stan.WYNIKI`
   (`("cb", "a", "zamkniety->otwarty")`) — zobaczysz je w `/diag`. Progi: 5 awarii, 30 s otwarcia.
5. Restart aplikacji, ponownie `PATCH` z kroku 2, powtórka kroku 3 z `-e WYNIK=ex11-po`. ⟨E11-PO⟩
   W `/diag` → `wyniki` szukaj wpisów `endpoint: "cb"`. W Tempo:
   ```
   {span.llm.cb.stan="otwarty"}
   ```
   U mnie (harness, ten sam scenariusz): p50 **19.8 s**, do `a` **80/80** → p50 **7.7 s**, do `a` **33/80**.
   Naprawa ma granicę: ~30 żądań było już w locie do `a`, zanim wyłącznik się otworzył — te zapłaciły
   pełne 15 s (p90 22 s).
6. `curl -s -X POST 127.0.0.1:8061/admin/reset` i `python check.py ex11`.

## Kryteria „done”
- [ ] Przy zawieszonym `a` mediana odpowiedzi spada poniżej 12 s, a do `a` trafia < 60% żądań.
- [ ] 429/529 NIE przełączają ruchu na `b` (sprawdź `_awaria`).
- [ ] Stan wyłącznika widać w trace (`llm.cb.stan`) i w `/diag`.
- [ ] `python check.py ex11` przechodzi.

## Pytania kontrolne
1. Dlaczego 529 nie może otwierać wyłącznika ani włączać fallbacku?
2. Co by się stało, gdyby w stanie półotwartym przepuścić do `a` wszystkie żądania zamiast jednego?
3. Wróć do ćw. 6, krok 8: jak wyłącznik zmienia skutki `PoolTimeout` przy włączonym fallbacku?

Odpowiedzi: `solutions/pytania_odpowiedzi.md`.

## ★ Bonus (opcjonalnie)
Dodaj gauge stanu wyłącznika (0/1/2) do metryk i panel w Grafanie obok `mock_llm_requests_total`
per dostawca. Ustaw `CB_OTWARCIE_S=5` i zobacz próbki półotwarte co 5 s w trakcie awarii.

---

## Mini-incydent III (po bloku III) — „dostawca mówi: przeciążenie; my mówimy: mamy mało ruchu”

> ~20 min. Diagnoza przez `/diag`, Prometheus i `/admin/stats` atrapy; bez kodu.

Dostawca przysłał zgłoszenie: w godzinach szczytu wasza aplikacja wysyła mu kilka razy więcej żądań,
niż macie użytkowników, i to falami. U was ruch to ~10 streszczeń/s.

1. Zatrzymaj własną aplikację i uruchom incydent (ustawia też profil atrapy `przeciazenie`):
   ```bash
   ./incydent.sh start mini-III
   docker compose run --rm -e WYNIK=mini-III k6 run -o experimental-prometheus-rw /scripts/otwarty.js -e RATE=10 -e CZAS=20s
   ```
2. Policz amplifikację (polecenie z ćw. 9, krok 4) i sprawdź statusy u dostawcy:
   ```bash
   curl -s 127.0.0.1:8061/admin/stats | python -m json.tool | head -20
   ```
   Prometheus: `sum(increase(llm_http_attempts_total[2m])) / sum(increase(app_requests_total{endpoint="summary"}[2m]))`.
   ⟨MINI3⟩
3. Odpowiedz bez kodu: ile prób HTTP na żądanie? Ile z nich to 529? Która warstwa ponawia (sprawdź
   `/diag` → `klienci`) i czy ponowienia coś ratują?
4. `python check.py ex09` — FAIL na incydencie. Potem `./incydent.sh stop`.

Odpowiedź: `solutions/pytania_odpowiedzi.md`, sekcja „Mini-incydenty”.

---
Utknąłeś? `solutions/hints/ex11_hint1.md` → `hint2` → `hint3`. Gotowe rozwiązanie:
`solutions/ex11_fallback.py` → `app/llm/fallback.py`.
