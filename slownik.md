# Słownik pojęć — kurs python-llm-perf

Alfabetyczny słowniczek terminów użytych w `exercises/00-teoria.md`, czytankach
blokowych (`01a`, `04a`, `08a`, `12a`, `14a`) i ćwiczeniach. Każde hasło: krótka
definicja + odnośnik do miejsca, w którym pojęcie wyjaśniono szerzej (`→ 00`,
`→ 01a`…) i do ćwiczeń, w których z niego korzystasz (`→ ćw. N`). Pełne
wyjaśnienia (definicja → intuicja → po co → częsta pomyłka) są w dokumentach
teoretycznych — tu tylko szybka ściąga.

Mapa ćwiczeń: ćw. 1–3 = pomiar i teoria kolejek (trace, model otwarty/zamknięty,
Little i kolano), ćw. 4–7 = asyncio, pule, procesy, ćw. 8–11 = dostawca (limity,
ponowienia, timeouty, fallback), ćw. 12–13 = backpressure i streaming,
ćw. 14–17 = kolejka zadań, cache, batching, porównanie z prawdziwym Claude,
ćw. 18 = finał.

---

**429 (Too Many Requests)** — odpowiedź dostawcy po przekroczeniu limitu RPM /
ITPM / OTPM; w SDK `anthropic.RateLimitError`, z nagłówkiem `retry-after`.
→ 00, 08a, ćw. 8.

**503 + Retry-After** — szybka odmowa *od aplikacji* przy pełnej kolejce albo po
przekroczeniu budżetu czekania; `Retry-After` mówi klientowi, kiedy wrócić.
Zdrowe zachowanie pod przeciążeniem, raportowane osobno od błędów. → 12a, ćw. 12.

**529 (overloaded)** — dostawca nie ma wolnej mocy (niezależnie od Twojego
limitu); w SDK 2.x `anthropic.OverloadedError`, która **nie** jest podklasą
`InternalServerError`. Przeciążenie, nie awaria — fallback go nie powinien
ponawiać. → 00, 08a, ćw. 9, 11, 14.

**Amplifikacja ponowień** — stosunek prób HTTP do dostawcy do żądań
użytkowników; warstwy się mnożą (3 próby aplikacji × 3 próby SDK = do 9).
Zmierzone: 3.65 bez kontroli, 1.20 z budżetem 20%. → 08a, ćw. 9.

**Anulowanie** — przerwanie zadania asyncio (`task.cancel()` →
`CancelledError` w miejscu czekania); jedyny sposób, by czekające wywołanie
oddało slot semafora, połączenie i generację u dostawcy. → 04a, 12a, ćw. 10, 18.

**anyio — limiter wątków** — domyślny limit 40 równoczesnych wątków dla
handlerów `def` i `run_in_threadpool` w FastAPI; ponad limit wywołania czekają
falami co 40, bez CPU i bez spanu. → 04a, ćw. 5.

**`asyncio.timeout`** — menedżer kontekstu z limitem całkowitym dla bloku
kodu; po przekroczeniu anuluje zadanie i rzuca `TimeoutError`. W kursie służy
jako deadline wywołania LLM. → 08a, ćw. 10.

**Atrapa LLM** — własny serwer zgodny z Messages API (port 8061) z
powtarzalnymi profilami: opóźnienia, limity, 429/529, streaming, ping,
wywołania minutowe; dwa „dostawcy” `a` i `b`. → 00, ćw. 1, 8–14, 17.

**Backlog gniazda** — kolejka połączeń w jądrze czekających na `accept()`;
przy przepełnieniu klient dostaje zerwane połączenie. Pod `gunicorn -k sync`
to w nim czeka nadmiar ruchu. → 04a, ćw. 7.

**Backoff wykładniczy** — przerwa przed ponowieniem rosnąca z numerem próby
(baza · 2ⁿ, z górnym limitem); bez jittera klienci wracają razem. → 08a, ćw. 9.

**Backpressure** — sygnał przeciążonej stacji do nadawcy, że ma zwolnić; w
HTTP praktycznie: kolejka ograniczona i odrzucanie nadmiaru. → 12a, ćw. 12.

**BaseHTTPMiddleware** — klasa za `@app.middleware("http")` w Starlette/FastAPI;
psuje `request.is_disconnected()` w handlerach, przez co anulowanie po
rozłączeniu przestaje działać. Middleware kursu jest czystym ASGI. → 12a, ćw. 10.

**Batching (wsad)** — sklejanie wielu próśb w jedno wywołanie LLM; parametry:
okno i maksymalny rozmiar, wsad ≈ min(λ · okno, max), latencja + ≤ okno.
Zmniejsza liczbę żądań, nie tokenów. → 14a, ćw. 16.

**Budżet czekania** — najdłuższy czas, jaki żądanie danej klasy może czekać na
slot (w kursie 5 s / 20 s); po nim dostaje 503 zamiast czekać dalej. → 12a, ćw. 12.

**Budżet ponowień** — globalny limit ponowień jako ułamek żądań w oknie
(w kursie 20% / 10 s); ogranicza amplifikację do ×1.2 przy masowej awarii.
→ 08a, ćw. 9.

**Budżet timeoutów** — ułożenie zegarów od środka: timeouty SDK (bezczynność)
< deadline aplikacji (per klasa) < timeouty warstw zewnętrznych (proxy, k6).
→ 08a, ćw. 10.

**Bulkhead (osobne pule)** — rozdzielenie slotów między klasy żądań (w kursie
32 krótkie / 16 długie), żeby jedna klasa nie zajęła zasobów drugiej; lekarstwo
na head-of-line blocking. → 01a, ćw. 12.

**Cache odpowiedzi** — wynik LLM przechowywany pod kluczem przez TTL (w
kursie FAQ w Redisie); trafienie nie woła dostawcy: λ_dostawca = (1 − h) · λ.
→ 14a, ćw. 15.

**Cache stampede (lawina)** — po wygaśnięciu klucza N równoczesnych chybień
woła LLM N razy; lekarstwo: single-flight. Zmierzone: 50 pytań → 50 wywołań.
→ 14a, ćw. 15, 18.

**`CancelledError`** — wyjątek, który anulowane zadanie dostaje w miejscu
`await`; dziedziczy po `BaseException`, więc `except Exception` go nie łapie
(i nie powinien). → 04a, ćw. 10.

**Circuit breaker (wyłącznik)** — automat stanów przed zawodnym dostawcą:
zamknięty → (N awarii) → otwarty przez T → półotwarty (jedna próbka) →
zamknięty albo znów otwarty. W kursie N = 5, T = 30 s. → 08a, ćw. 11.

**Coordinated omission** — błąd pomiaru modelu zamkniętego: generator czeka
na wolny system, więc nie mierzy żądań, które w prawdziwym ruchu czekałyby w
kolejce. Zmierzone: p99 1.57 s (zamknięty) vs 4.41 s (otwarty). → 00, ćw. 2.

**Czas obsługi (S)** — czas, w którym zasób faktycznie pracuje dla żądania (tu:
wywołanie LLM); podstawa rachunku pojemności X_max = c / S. → 00, 01a, ćw. 1, 3.

**Czekanie (W_q)** — czas, w którym żądanie stoi w kolejce do zasobu (slot,
połączenie, wątek); niewidoczne w profilu, widoczne w trace i metrykach
(`llm_queue_wait_seconds`). → 00, ćw. 1, 6.

**Deadline** — bezwzględny limit czasu całego żądania (czekanie + wywołanie +
ponowienia), po którym wynik traci wartość; w kursie per klasa: 30 s / 330 s.
→ 08a, 12a, ćw. 10, 12.

**Dopływ (λ)** — intensywność przychodzenia żądań; w systemie przeciążonym
większa niż przepustowość, a różnica trafia do kolejki. → 00, ćw. 2, 3.

**Drain (opróżnianie)** — czas od końca dopływu do pustych kolejek; ≈
zaległość / pojemność. Przy wywołaniach minutowych liczony w minutach (ćw. 12:
213–402 s). → 00, 01a, ćw. 12, 18.

**`dropped_iterations`** — licznik k6 w modelu otwartym: żądania, których
generator nie zdążył wysłać o czasie (brak VU); niezerowy = pomiar nieważny.
→ 00, ćw. 2, 3.

**Erlang C (M/M/c)** — model kolejki z c serwerami i wspólną kolejką; wzór
Erlanga C daje prawdopodobieństwo czekania. Więcej serwerów = kolano bliżej
ρ = 1 i ostrzejsze. → 00, 01a, ćw. 3.

**Fallback** — przełączenie na zapasowego dostawcę przy awarii głównego; bez
wyłącznika każde żądanie płaci timeout martwego dostawcy (zmierzone p50 19.8 s).
→ 08a, ćw. 11.

**GIL** — globalna blokada interpretera CPython: kod Pythona wykonuje naraz
jeden wątek; czekanie na I/O ją zwalnia. → 04a, ćw. 4, 5.

**`gracefulStop` (k6)** — czas, przez jaki k6 po końcu scenariusza czeka na
żądania w toku (domyślnie 30 s); krótszy od najdłuższego żądania zrywa
wielominutowe wywołania i fałszuje drain. → 00, ćw. 10, 12.

**gunicorn** — menedżer procesów; `-k sync` = jedno żądanie na proces i
domyślny `--timeout 30` zabijający worker, `-k uvicorn_worker.UvicornWorker` =
pętla asyncio w każdym procesie. → 04a, ćw. 7.

**Head-of-line blocking** — krótkie żądania czekają za długimi we wspólnej
kolejce i puli; zmierzone: krótkie czekają p50 29 s przy obsłudze ~1 s.
→ 01a, ćw. 12.

**Histogram** — metryka z kubełkami wartości; z niego liczysz percentyle
(`histogram_quantile`). Kubełki muszą sięgać najdłuższych czasów (u atrapy do
300 s). → 00, ćw. 1, 3.

**`http_req_waiting` (k6)** — czas do pierwszego bajtu odpowiedzi; przy SSE =
czas do nagłówków, więc buforowania strumienia nie widzi. → 12a, ćw. 13.

**httpx2** — klient HTTP, na którym stoi SDK `anthropic` 2.x; instrumentacja
`HTTPX2ClientInstrumentor` daje span `POST` per próba HTTP. Domyślne `Limits`
100 / 20, w SDK `max_connections=1000`. → 04a, ćw. 1, 6.

**ITPM** — limit tokenów wejścia na minutę; najłatwiej przekraczany dużymi
wsadami i długimi promptami. → 00, 08a, 14a, ćw. 8, 16.

**Jitter** — losowe rozrzucenie przerwy przed ponowieniem; pełny jitter:
U(0, min(limit, baza · 2ⁿ)). Rozbija zsynchronizowane fale ponowień. → 08a, ćw. 9.

**Kolano krzywej** — obszar wykorzystania, w którym czas czekania zaczyna
rosnąć szybciej niż obciążenie; dla 32 slotów zmierzone ok. 28–30/s. → 00, 01a,
ćw. 3.

**Kolejka ograniczona** — kolejka o maksymalnej długości K; nadmiar dostaje od
razu odmowę. K ≈ akceptowalne czekanie × pojemność. → 12a, ćw. 12.

**Kolejka zadań** — broker (Redis Streams) między producentem (aplikacją) a
workerem; przesuwa pracę w czasie, nie dodaje mocy. → 14a, ćw. 14.

**Korutyna** — funkcja `async def`; wykonuje się do najbliższego `await`, potem
oddaje sterowanie pętli. Zawieszona nie zużywa wątku ani CPU. → 04a, ćw. 4.

**Kubełek z żetonami (token bucket)** — model limitu: kubełek o pojemności =
limit, stale dopełniany; żądanie zabiera żetony, brak żetonów = 429.
→ 08a, ćw. 8.

**Lag kolejki** — liczba wpisów strumienia jeszcze nieodebranych przez grupę
konsumentów (`XINFO GROUPS`); prawdziwa długość kolejki zadań (`kolejka_lag`).
→ 14a, ćw. 14.

**Lag pętli zdarzeń** — opóźnienie, z jakim pętla wykonuje zaplanowany
callback; sekundy = pętla zablokowana (`app_event_loop_lag_seconds`, `/diag`).
→ 04a, ćw. 4.

**Latencja (R)** — czas odpowiedzi jednego żądania = czekanie + obsługa; mierzona
po stronie klienta i serwera (to różne liczby). → 00.

**Limiter tempa** — ograniczenie po stronie klienta dopasowane do limitów
dostawcy (z nagłówków `anthropic-ratelimit-*`); zamienia 429 w czekanie u nas.
→ 08a, ćw. 8.

**Little (prawo)** — L = λ · W dla każdego stabilnego systemu i każdej stacji;
stąd pojemność c / S, rozmiar puli λ · S i kontrola spójności pomiarów.
→ 00, 01a, ćw. 3, 6, 7, 14.

**`llm.queue_wait`** — span czekania na semafor LLM, rodzeństwo spanu
`llm.call` (nie rodzic); plus atrybut `llm.queue.wait_ms` na spanie żądania.
→ 00, ćw. 1.

**Load shedding (odrzucanie nadmiaru)** — świadome, szybkie odrzucanie części
ruchu przy przeciążeniu, żeby reszta była obsłużona w rozsądnym czasie.
→ 12a, ćw. 12.

**`max_retries` (SDK)** — liczba ponowień SDK `anthropic`, domyślnie 2 (3 próby),
z przerwami 0.5–8 s i honorowaniem `retry-after`; przy własnej warstwie
ponowień ustaw 0. → 08a, ćw. 9, 10.

**Metastabilność** — stan, w którym system zostaje przeciążony po ustąpieniu
przyczyny, bo sam generuje nadmiar (np. ponowieniami). → 08a, ćw. 9.

**M/M/1** — najprostszy model kolejki (dopływ Poissona, wykładnicza obsługa,
jeden serwer); W = S / (1 − ρ): przy ρ = 0.9 czas pobytu to 10 × S. → 00, ćw. 3.

**Model otwarty** — generator wysyła w zadanym tempie niezależnie od
odpowiedzi (k6 `constant-arrival-rate`, `ramping-arrival-rate`); pokazuje
kolejki tak, jak prawdziwy ruch. → 00, ćw. 2, 3.

**Model zamknięty** — stała liczba użytkowników czekających na odpowiedź (k6
`constant-vus`); X = N / (R + Z), sam zwalnia pod obciążeniem. → 00, ćw. 2.

**Ogon rozkładu** — górne percentyle (p99, max); w aplikacji LLM częściowo
zaprojektowany (klasa wywołań minutowych), dlatego raportowany per klasa.
→ 00, ćw. 2, 12.

**OTPM** — limit tokenów wyjścia na minutę; profil `limity` atrapy: 12 000 →
60 streszczeń po 200 tokenów na minutę. → 00, 08a, ćw. 8.

**Pending** — wpisy odebrane przez workera, ale niepotwierdzone (`XPENDING`):
w toku + pobrane na zapas; zdrowo ≈ współbieżność workera. → 14a, ćw. 14.

**Percentyl** — wartość, poniżej której leży p% pomiarów (p50, p99); nie wolno
uśredniać percentyli między instancjami. → 00, ćw. 2, 3.

**Pętla zdarzeń** — jedyny wątek asyncio, który budzi korutyny gotowe do
działania; dla kodu między `await`ami to stacja z jednym serwerem. → 04a, ćw. 4.

**Ping (SSE)** — puste zdarzenie strumienia wysyłane przez dostawcę (w atrapie
co 15 s); resetuje read timeout podczas ciszy; iterator `MessageStream` SDK go
nie zwraca. → 08a, ćw. 10.

**Planowanie pojemności** — c = ⌈λ_szczyt · S / ρ_cel⌉ z ρ_cel 0.7–0.8, plus
sprawdzenie sufitów (limity i moc dostawcy), których slotami nie podniesiesz.
→ 01a, ćw. 3, 6.

**Pojemność (X_max)** — największa utrzymywalna przepustowość stacji: c / S;
pojemność ścieżki = minimum po stacjach. → 00, 01a, ćw. 3.

**`PoolTimeout`** — przekroczenie `pool` timeoutu przy czekaniu na połączenie w
puli httpx2; w SDK wychodzi jako `APITimeoutError` (podklasa
`APIConnectionError`). → 04a, ćw. 6.

**Prefetch** — pobieranie przez workera zadań na zapas (taskiq-redis:
`xread_count`); ukrywa kolejkę (lag = 0) i zawłaszcza pracę w jednym procesie.
→ 14a, ćw. 14.

**Profil CPU vs wall** — profil CPU próbkuje wątki liczące, wall — wszystkie
(także czekające w blokującym wywołaniu). Zawieszonej korutyny nie widzi żaden.
→ 00, ćw. 4.

**Przepustowość (X)** — ile żądań na sekundę system **kończy**; raportuj
osiągniętą, nie zadaną. → 00, ćw. 2, 4.

**Pula połączeń** — zbiór połączeń TCP klienta HTTP (`max_connections`,
`max_keepalive_connections`); mniejsza niż semafor tworzy ukrytą kolejkę.
→ 04a, ćw. 6.

**Pula wątków** — wątki wykonujące kod synchroniczny poza pętlą; w FastAPI
ograniczona limiterem anyio (40). → 04a, ćw. 5.

**Read timeout** — limit **bezczynności** odczytu (każdy bajt resetuje zegar),
nie limit całkowity: strumień 150 s przy read 30 s kończy się poprawnie.
→ 08a, ćw. 10.

**`ReadTimeout` (httpx2)** — wyjątek timeoutu odczytu; w trakcie strumienia SDK
wypuszcza go **surowo** (nie jako `APITimeoutError`) i nie ponawia. → 08a, ćw. 10.

**RED** — metryki usługi: tempo (Rate), błędy (Errors), czas (Duration).
→ 00, ćw. 1, 18.

**Redis Streams** — dziennik wpisów z grupami konsumentów (`XADD`,
`XREADGROUP`, `XACK`, `XINFO GROUPS`, `XPENDING`); broker kolejki zadań
w kursie. → 14a, ćw. 14.

**`retry-after`** — nagłówek z liczbą sekund do ponownej próby; od dostawcy
(429/529) ma pierwszeństwo przed własnym backoffem, od aplikacji (503) —
obowiązuje Twoich klientów. → 08a, 12a, ćw. 8, 9, 12.

**RPM** — limit żądań na minutę u dostawcy. → 00, 08a, ćw. 8.

**Semafor** — `asyncio.Semaphore(n)`: jawny limit współbieżności z kolejką
czekających; w kursie sloty LLM per klasa z mierzonym czasem czekania.
→ 04a, ćw. 1, 6, 12.

**Server-Timing** — nagłówek odpowiedzi aplikacji z czasem czekania i wywołania
LLM; z niego k6 liczy trendy `app_*` (np. czekanie krótkich). → ćw. 2, 12.

**Single-flight** — przy chybieniu cache liczy tylko pierwsze żądanie, reszta
czeka na jego wynik (`asyncio.Future` w procesie, `SET NX PX` w Redisie między
procesami). → 14a, ćw. 15.

**Slot** — jedno miejsce w limicie współbieżności (semafor, pula); zajęty przez
cały czas obsługi — przy wywołaniach minutowych przez minuty. → 00, ćw. 6, 12.

**Span** — odcinek trace z początkiem, końcem, atrybutami i rodzicem; luki
między spanami to czas, którego nikt nie zarejestrował. → 00, ćw. 1.

**SSE (Server-Sent Events)** — strumień zdarzeń tekstowych w jednej odpowiedzi
HTTP (`text/event-stream`); tak dostawca i aplikacja przesyłają odpowiedź
kawałkami. → 12a, ćw. 13.

**Stan ustalony** — okres, w którym średnie przestały się zmieniać; przychodzi
po kilku W (przy analizach — po minutach); przy λ > X_max nie istnieje.
→ 01a, ćw. 3, 12.

**Strażnik rozłączenia** — zadanie obok wywołania LLM sprawdzające
`request.is_disconnected()` (w kursie co 0.5 s); po rozłączeniu anuluje
wywołanie. → 12a, ćw. 10.

**Streaming buforowany** — ktoś po drodze zbiera fragmenty strumienia i wysyła
je na końcu; TTFT dostawcy OK, klient czeka na całość (zmierzone: 100% czasu
vs 19%). → 12a, ćw. 13, 18.

**taskiq** — biblioteka kolejki zadań z zadaniami `async def`; współbieżność
workera = `--workers` × `--max-async-tasks` (domyślnie 2 × 100). → 14a, ćw. 14.

**Timeout k6** — domyślny limit czasu żądania w k6: 60 s; testy wielominutowe
muszą ustawiać `params.timeout` (inaczej `status 0` po 60 s). → 08a, ćw. 10, 12.

**Tokeny/s** — tempo generacji po pierwszym tokenie (realnie ~225–300, atrapa
250); czas całkowity ≈ TTFT + tokeny / tempo. → 00, ćw. 17.

**Trace** — drzewo spanów jednego żądania; pokazuje, gdzie żądanie spędziło
czas, łącznie z czekaniem. → 00, ćw. 1.

**TTFT (time to first token)** — czas do pierwszego fragmentu odpowiedzi;
inny u dostawcy (`llm_ttft_seconds`), inny wysłany klientowi
(`app_stream_first_chunk_seconds`), inny u klienta. → 00, 12a, ćw. 10, 13, 17.

**USE** — metryki zasobu: zajętość (Utilization), nasycenie (Saturation), błędy
(Errors). → 00, ćw. 6, 18.

**UvicornWorker** — worker gunicorna (`uvicorn_worker.UvicornWorker`) z pętlą
asyncio; timeout gunicorna nie przerywa jego żądań (zmierzone: 90 s → 200).
→ 04a, ćw. 7.

**Wąskie gardło** — stacja o najmniejszej pojemności na ścieżce; tylko jej
poszerzenie zwiększa przepustowość. → 01a, ćw. 6, 8.

**Wiek najstarszego** — jak długo czeka najstarsze żądanie / zadanie
(`llm_oldest_waiting_age_seconds`, `kolejka_wiek_najstarszego_s`,
`mock_llm_oldest_inflight_seconds`); najlepszy sygnał SLO kolejki.
→ 00, 14a, ćw. 12, 14.

**`WORKER TIMEOUT`** — komunikat gunicorna po zabiciu workera sync, który nie
odpowiedział w `--timeout` (domyślnie 30 s); klient dostaje 500. → 04a, ćw. 7.

**Współbieżność (L)** — liczba żądań w systemie naraz (czekających i
obsługiwanych). → 00, ćw. 3.

**Wykorzystanie (ρ)** — odsetek czasu pracy serwerów stacji: ρ = λ · S / c;
czekanie rośnie jak 1 / (1 − ρ). → 00, 01a, ćw. 3.

**Wywołanie wielominutowe** — wywołanie LLM trwające 60–300 s (długi TTFT,
długi strumień, pauzy); zajmuje sloty minutami i mnoży koszt każdego błędu
timeoutu i ponowienia. → 00, 01a, 08a, ćw. 10, 12.

**XLEN** — liczba wpisów w strumieniu Redis; taskiq nie usuwa wpisów, więc
XLEN ≠ długość kolejki (patrz: lag kolejki). → 14a, ćw. 14.

**Zaległość** — liczba żądań czekających i w toku w chwili końca dopływu;
raportowana razem z wiekiem najstarszego i czasem drain. → 00, ćw. 12, 18.
