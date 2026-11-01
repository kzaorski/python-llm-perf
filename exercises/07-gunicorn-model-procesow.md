# Ćwiczenie 7: gunicorn — workery synchroniczne czy UvicornWorker, i ile procesów

> Czas: ~45 min (dwa przebiegi po 30 s + test wywołania 90 s na każdym wariancie) + mini-incydent II ~20 min

> Blok II. Czytanka `04a-asyncio-petla-i-pule.md` (procesy, wątki, korutyny — kto obsługuje ile żądań naraz).

## Cel
Wariant produkcyjny aplikacji ma stać za gunicornem (port 8062). Obecna konfiguracja
(`gunicorn.conf.py`) jest skopiowana z poradnika dla aplikacji CPU-bound: workery synchroniczne,
`2 × CPU + 1` procesów, domyślny `timeout 30`. Mierzysz, co to znaczy dla aplikacji, która głównie
CZEKA na LLM: przepustowość, pamięć, kolejka w backlogu gniazda i wywołanie dłuższe niż 30 s.
Przestawiasz gunicorna na `UvicornWorker` z liczbą procesów dobraną do zadania.

## Teoria w pigułce
- **Worker sync** — jeden proces = jedno żądanie naraz. Przepustowość = liczba workerów / czas
  wywołania. Przy wywołaniu LLM 3.5 s i 29 procesach: ≤ 8.3 żądania/s, a każdy proces trzyma pełną
  kopię aplikacji w pamięci. Nadmiar czeka w backlogu gniazda (poza aplikacją) albo dostaje zerwane
  połączenie. Pułapka: wzór `2 × CPU + 1` zakłada pracę na CPU — przy I/O nie ma z liczbą rdzeni nic wspólnego.
- **UvicornWorker** — proces gunicorna z pętlą asyncio; uruchamia aplikację ASGI (`app.main:app`) i
  obsługuje setki żądań naraz. Liczbę procesów dobierasz do CPU (serializacja JSON, TLS, telemetria) i
  odporności na awarię, a współbieżność LLM — semaforem.
- **Semafor jest per proces.** `LLM_SLOTY=32` × 2 procesy = 64 wywołania naraz. Sumę trzymaj ≤ mocy
  i limitom dostawcy. Pułapka: dokładasz procesy „dla wydajności” i nieświadomie mnożysz ruch do dostawcy.
- **`timeout` gunicorna** — dla workerów sync: maksymalny czas obsługi żądania; po nim master zabija
  worker (`WORKER TIMEOUT`, klient dostaje 500). Dla UvicornWorker: limit braku heartbeatu procesu
  (zablokowana pętla), a nie czas żądania. Przy wywołaniach 60–300 s to różnica „działa” / „nie działa”.

## Kroki
1. Niczego nie zatrzymujesz — gunicorn słucha na 8062, aplikacja z ćw. 1–6 może dalej działać na 8060.
   Ile masz rdzeni? `python -c "import os; print(os.cpu_count())"` — tyle × 2 + 1 procesów uruchomi
   obecna konfiguracja.
2. Uruchom wariant obecny (terminal T3):
   ```bash
   gunicorn -c gunicorn.conf.py
   ```
   T2: `curl -s 127.0.0.1:8062/health` → `"serwer": "gunicorn-wsgi"`. Pamięć wszystkich procesów:
   ```bash
   ps -axo pid=,ppid=,rss=,command= | grep '[g]unicorn -c' | awk '{s+=$3} END {print NR " procesów, " int(s/1024) " MB RSS"}'
   ```
3. **Hipoteza:** ruch otwarty 15/s przez 30 s, każde wywołanie ~3.5 s (`TOTAL_S=3` ustawia czas
   generowania u atrapy). L = λ·W = ? Ile żądań/s obsłuży Twoja liczba workerów sync? Co stanie się z resztą?
   ```bash
   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/gunicorn.js -e RATE=15 -e CZAS=30s -e TOTAL_S=3 -e WARIANT=sync
   ```
   U mnie (26 procesów, 1658 MB RSS): 384 × 200 i **67 × `status 0`** (połączenie zerwane — backlog
   gniazda pełny), p50 11.4 / p99 19.6 s, test 49.6 s przy 30 s dopływu.
4. **Wywołanie dłuższe niż 30 s** (atrapa milczy 90 s przed pierwszym tokenem):
   ```bash
   curl -s -o /dev/null -w '%{http_code} po %{time_total} s\n' -X POST -H 'x-mock-ttft-ms: 90000' 127.0.0.1:8062/claims/1/summary
   ```
   W logu gunicorna (T3) szukaj `WORKER TIMEOUT`. U mnie: `500 po 30.9 s`, w logu 1 × `WORKER TIMEOUT`.
5. Zatrzymaj gunicorna (Ctrl+C w T3). Otwórz **`gunicorn.conf.py`** i przestaw go na:
   `worker_class = "uvicorn_worker.UvicornWorker"`, `wsgi_app = "app.main:app"` (ta sama aplikacja co
   na 8060), 2 procesy, `LLM_SLOTY` per proces w `raw_env` tak, by suma ≤ moc atrapy (64), oraz
   `APP_WARIANT=gunicorn-uvicorn` w `raw_env` (po tym check rozpozna wariant). Zostaw komentarz,
   dlaczego tyle procesów.
6. Uruchom ponownie, sprawdź `/health` (`"serwer": "gunicorn-uvicorn"`) i pamięć (krok 2), powtórz
   kroki 3–4 z `-e WARIANT=uvicorn`. U mnie (3 procesy z masterem, 361 MB RSS): **451 × 200**, 0 zerwanych,
   p50 5.6 / p99 11.6 s, czekanie na slot p50 2.2 / p99 8.0 s; wywołanie 90 s → **200 po 90.9 s**. Czekanie
   na slot mimo 2 × 32 ≥ L ≈ 15 × 3.5 = 52 to nierówny podział połączeń między procesy (pytanie 3) — w innym
   przebiegu (tabela niżej) wyszło p50 3.9 s; licz z zapasem.

   U mnie (harness, ten sam ruch):

   | | procesy / RSS | osiągnięte | p50 | zerwane | ostatnia | wywołanie 90 s |
   |---|---|---|---|---|---|---|
   | sync, 2×CPU+1 | 29 / **2111 MB** | 9.05/s | 11.3 s | **63/450** | po 49.7 s | **500 po 30.3 s** (`WORKER TIMEOUT`) |
   | UvicornWorker ×2 (32 sloty/proces) | 2 / **317 MB** | **13.0/s** | 3.9 s (p99 5.1 s) | 0/450 | po 34.6 s | **200 po 90.6 s** |

7. `python check.py ex07` (gunicorn musi działać na 8062).

## Kryteria „done”
- [ ] `/health` na 8062 zgłasza `gunicorn-uvicorn`; 40 równoległych żądań po ~2.1 s kończy się jedną falą.
- [ ] Wywołanie 90 s przez gunicorna kończy się 200, nie 500.
- [ ] Liczbę procesów i slotów na proces umiesz uzasadnić (CPU vs współbieżność vs moc dostawcy).
- [ ] `python check.py ex07` przechodzi.

## Pytania kontrolne
1. Dlaczego w wariancie sync część żądań skończyła się zerwanym połączeniem, a nie 503 od aplikacji?
2. Podnosisz `timeout` workerów sync do 600 s. Co naprawiasz, a co nadal jest nie tak?
3. Masz 2 procesy UvicornWorker po 32 sloty. Czy 64 żądania naraz zawsze rozłożą się po 32 na proces?
   Jak to wpływa na czekanie na slot?

Odpowiedzi: `solutions/pytania_odpowiedzi.md`.

## ★ Bonus (opcjonalnie)
Uruchom UvicornWorker z 8 procesami po 32 sloty i puść ruch 30/s z `TOTAL_S=3` przy profilu atrapy
`przeciazenie` (`curl -X POST 127.0.0.1:8061/admin/profile/przeciazenie`). Co pokazuje
`sum by (status) (increase(mock_llm_requests_total[2m]))`? Zresetuj atrapę: `curl -X POST 127.0.0.1:8061/admin/reset`.

---

## Mini-incydent II (po bloku II) — „pisma do klientów raz szybkie, raz dwa razy wolniejsze”

> ~20 min. Diagnoza przez pomiar i `/diag`, bez czytania kodu w `.run/incydent-*`.

Dział obsługi zgłasza: w godzinach szczytu, gdy wysyłają pisma seryjnie (kilkadziesiąt naraz), część
pism generuje się ~2 s, a część ~4 s — nigdy pośrodku. Klasyfikacje i streszczenia w tym czasie działają normalnie.

1. Zatrzymaj własną aplikację na 8060 (gunicorn na 8062 może zostać) i uruchom incydent:
   ```bash
   ./incydent.sh start mini-II
   ```
2. Odtwórz problem (fala z ćw. 5) i sprawdź responsywność procesu w jej trakcie:
   ```bash
   seq 60 | xargs -P 60 -I{} curl -s -o /dev/null -w '%{time_total}\n' -X POST \
     -H 'x-mock-ttft-ms: 2000' -H 'x-mock-total-s: 0.1' 127.0.0.1:8060/claims/{}/letter | sort -n | awk '{printf "%.2f ", $1} END {print ""}'
   curl -s -o /dev/null -w 'ping: %{time_total}\n' 127.0.0.1:8060/diag/ping
   ```
   U mnie: 60 × 200; najszybsze 2.27 s, mediana 2.45 s, najwolniejsze 4.54 s — dwie grupy (~2.3 s i ~4.4 s);
   ping w trakcie fali 1.3 ms. `check.py ex05`: „20 z 60 żądań czekało na drugą falę (min 2.16 s, max 4.36 s)”.
3. Odpowiedz bez kodu: ile żądań w pierwszej fali? Czy pętla zdarzeń stoi (ping)? Czy to semafor LLM
   (`/diag` → `kolejka`)? Jaki zasób ma dokładnie taki limit?
4. Sprawdzenie: `python check.py ex05` — FAIL na incydencie.
5. `./incydent.sh stop` i z powrotem własna aplikacja.

Odpowiedź: `solutions/pytania_odpowiedzi.md`, sekcja „Mini-incydenty”.

---
Utknąłeś? `solutions/hints/ex07_hint1.md` → `hint2` → `hint3`. Gotowe rozwiązanie:
`solutions/ex07_gunicorn.py` → `gunicorn.conf.py`.
