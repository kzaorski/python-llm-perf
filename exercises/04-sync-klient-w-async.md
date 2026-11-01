# Ćwiczenie 4: Synchroniczny klient LLM w handlerze `async` — proces, który obsługuje jedno żądanie naraz

> Czas: ~45 min (dwa przebiegi ruchu otwartego po 30 s, pierwszy kończy się po ~1.5 min)

> Blok II — asyncio, pule, procesy (ćw. 4–7). Najpierw przeczytaj czytankę
> `04a-asyncio-petla-i-pule.md` (pętla zdarzeń, `await`, pula wątków anyio, procesy).

## Cel
Endpoint klasyfikacji zgłoszeń (`POST /claims/{n}/classify`) woła LLM synchronicznym klientem
wewnątrz `async def`. Patrzysz na to od strony systemu pod obciążeniem: ile żądań/s proces naprawdę
obsługuje, gdzie rośnie kolejka (i dlaczego NIE na semaforze), co dzieje się z innymi endpointami
i z `/health`. Profil i lag pętli to tylko potwierdzenie. Naprawiasz klasyfikację ścieżką asynchroniczną.

## Teoria w pigułce
- **Pętla zdarzeń** — jeden wątek, który na zmianę wykonuje wszystkie korutyny procesu. Korutyna oddaje
  pętlę tylko na `await`. Po co: tysiące żądań czekających na I/O w jednym wątku. Pułapka: wywołanie
  blokujące (synchroniczne I/O, `time.sleep`) w `async def` nie oddaje pętli — stoi CAŁY proces.
  (→ `04a`; `00-teoria.md` „System jako sieć kolejek”)
- **Przepustowość procesu przy blokadzie** = 1 / czas wywołania. Klasyfikacja trwa ~0.5 s, więc proces
  z zablokowaną pętlą robi ≤ 2 żądania/s — bez względu na sloty, rdzenie i dostawcę.
- **Gdzie wtedy jest kolejka?** Nie na semaforze (żądania do niego nie docierają), tylko przed pętlą:
  w gnieździe nasłuchującym i w zadaniach, które czekają na swoją kolej w pętli. `llm_waiting` = 0,
  `Server-Timing: czekanie` = 0 — a klient czeka dziesiątki sekund. Pułapka: metryki aplikacji, które
  mierzą od wejścia do handlera, tego czekania nie widzą.
- **Lag pętli** — o ile później niż zaplanowano budzi się `asyncio.sleep(0.1)`. Przy blokadzie rośnie
  do czasu wywołania. Profil **wall** (zegar ścienny) pokazuje, gdzie wątek stoi; profil **CPU** — że nic
  nie liczy. To potwierdzenie przyczyny, nie objaw dla użytkownika.

## Kroki
1. Stan: aplikacja po ćw. 1–3 na 8060. Sprawdź pojedynczo: `curl -s -X POST 127.0.0.1:8060/claims/7/classify`
   — ~0.5 s, działa. Pojedyncze żądanie nie zdradza wady.
2. **Hipoteza:** ruch otwarty 6 żądań/s klasyfikacji przez 30 s. Ile żądań/s obsłuży proces? Kiedy
   przyjdzie ostatnia odpowiedź? Co pokaże `Server-Timing: czekanie`?
3. W drugim terminalu mierz responsywność procesu (endpoint bez I/O — czas = czekanie na pętlę):
   ```bash
   for i in $(seq 1 60); do curl -s -o /dev/null -w '%{time_total}\n' 127.0.0.1:8060/diag/ping; sleep 0.5; done | sort -n | tail -3
   ```
   i równocześnie ruch otwarty (scenariusz z ćw. 7, tu skierowany na port 8060):
   ```bash
   docker compose run --rm -e WYNIK=ex04-przed k6 run -o experimental-prometheus-rw /scripts/gunicorn.js \
     -e GUNICORN_URL=http://host.docker.internal:8060 -e SCIEZKA=classify -e RATE=6 -e CZAS=30s
   ```
   U mnie (dokładnie te polecenia): k6 181 żądań, 179 × 200 + 2 × `status 0`, p50 **33.8 s**, p99 **69.0 s**,
   test trwał 99.8 s przy 30 s dopływu; najwolniejszy `/diag/ping` **54.5 s**; `/diag` → kolejka LLM pusta
   (`czekajace` 0) — czekanie nie jest na semaforze.
4. Grafana → Prometheus:
   ```
   sum by (endpoint) (rate(app_requests_total[1m]))
   max_over_time(llm_inflight{klasa="krotkie"}[2m])
   histogram_quantile(0.99, sum by (le) (rate(app_event_loop_lag_seconds_bucket[1m])))
   ```
   Klasyfikacja nie przechodzi przez semafor, więc `llm_inflight` = 0, a lag pętli rośnie do czasu
   wywołania. W Tempo trace `POST /claims/{n}/classify` NIE ma spanu `llm.call` — tylko `POST` klienta
   HTTP, a między kolejnymi żądaniami widać, że wykonują się ściśle jedno po drugim.
5. **Potwierdzenie profilem (opcjonalne, ~5 min).** Uruchom aplikację z profilerem w trybie wall:
   ```bash
   PYROSCOPE=1 PYROSCOPE_WALL=1 uvicorn app.main:app --port 8060
   ```
   powtórz krok 3 i w Grafanie: Explore → Pyroscope → `claims-assistant`, etykieta `tryb=wall`.
   Gorąca ścieżka wall prowadzi z `klasyfikuj` przez synchroniczny klient do oczekiwania na gnieździe.
   ⟨E04-PROFIL⟩
6. Otwórz **`app/klasyfikacja.py`** (`TODO ćw. 04`). Zamień synchroniczne wywołanie na ścieżkę
   asynchroniczną aplikacji: `await obsluga.wykonaj(request, Zadanie(klasa="krotkie", ...))`. Dostajesz
   przy okazji wszystko, co ma ścieżka LLM: slot, pomiar czekania, telemetrię, wynik żądania.
7. Restart (bez profilera) i powtórka kroku 3 z `-e WYNIK=ex04-po`. U mnie: 181 × 200, 5.93/s, p50 0.53 s,
   p99 1.01 s, test 30.5 s; najwolniejszy `/diag/ping` 4.8 ms.
8. `python check.py ex04` (ruch otwarty 6/s na `/classify` + pomiar `/diag/ping` w tle).

U mnie (pomiar harnessem: 6/s klasyfikacji + 2/s streszczeń w tle, 30 s):

| | osiągnięte tempo | classify p50 / p99 | `/diag/ping` | ostatnia odpowiedź |
|---|---|---|---|---|
| przed | 2.05/s, 22/180 zerwanych | 33.7 / 62.1 s | p50 2.3 s, max 10.9 s | po 87.9 s |
| po | 5.89/s, 0 błędów | 0.51 / 1.00 s | p99 13 ms | po 30.5 s |

Streszczenia w tle (inny endpoint, ten sam proces): p50 37.8 s → 1.09 s.

## Kryteria „done”
- [ ] Proces przy ruchu otwartym 6/s nadąża (osiągnięte tempo ≈ dopływ), `/diag/ping` odpowiada w ms.
- [ ] Umiesz wyjaśnić, dlaczego przed naprawą `Server-Timing: czekanie` = 0, a klient czekał minutę.
- [ ] `python check.py ex04` przechodzi.

## Pytania kontrolne
1. Przed naprawą: dlaczego zwiększenie `LLM_SLOTY` nic by nie dało?
2. Dlaczego zwolniły też streszczenia i `/health`, które nie używają klasyfikacji?
3. Ile procesów uvicorn trzeba by uruchomić, żeby z blokującym klientem obsłużyć 6/s? Dlaczego to zła naprawa?

Odpowiedzi: `solutions/pytania_odpowiedzi.md`.

## ★ Bonus (opcjonalnie)
Zamiast przepisywać na `async`, owiń synchroniczne wywołanie w `await asyncio.to_thread(...)`. Zmierz
ruch 6/s i 60/s. Co ogranicza przepustowość w tym wariancie? (Podpowiedź: ćw. 5.)

---
Utknąłeś? `solutions/hints/ex04_hint1.md` → `hint2` → `hint3`. Gotowe rozwiązanie:
`solutions/ex04_klasyfikacja.py` → `app/klasyfikacja.py`.
