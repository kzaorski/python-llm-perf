# 12a. Czytanka: backpressure, odrzucanie nadmiaru i streaming

Czytanka, nie ćwiczenie — bez zadań i kryteriów „done”. Cel: zrozumieć, co
system powinien robić, **gdy dopływ przekracza pojemność** — i dlaczego „niech
czekają” jest najgorszą z odpowiedzi przy wywołaniach trwających minuty. Druga
część: streaming odpowiedzi (SSE), czyli jak mierzyć to, co użytkownik
naprawdę czuje — czas do pierwszego fragmentu. Każde pojęcie w schemacie:

> **Definicja** → **Intuicja/analogia** → **Po co to** → **Częsta pomyłka**

Wracaj tu, gdy coś przestanie się spinać. Krótkie definicje są w `slownik.md`.

---

## Backpressure

**Definicja.** **Backpressure** (przeciwciśnienie) to mechanizm, którym
przeciążona stacja **sygnalizuje nadawcy**, że ma zwolnić. Przy λ > X_max
(00-teoria) system ma tylko trzy wyjścia:
1. **Kolejkować bez limitu** — przyjąć wszystko, czas czekania rośnie bez
   końca, pamięć też (to *brak* backpressure).
2. **Blokować nadawcę** — nie przyjmować nowego żądania, dopóki nie ma miejsca
   (backpressure „w górę”: zapełniony backlog gniazda, zamknięty model ruchu).
3. **Odrzucać nadmiar** (*load shedding*) — szybko odmówić części żądań, żeby
   reszta została obsłużona w rozsądnym czasie.

W HTTP z klientami spoza Twojej kontroli realny wybór to 1 albo 3.

**Intuicja.** Klub z bramkarzem. Bez bramkarza wpuszcza się wszystkich, w
środku nie da się oddychać i nikt nie dostaje drinka. Z bramkarzem część osób
słyszy przy drzwiach „pełno, wróćcie za 20 minut” — a ci w środku bawią się
normalnie.

**Po co to.** Kolejka bez limitu nie zwiększa pojemności — zmienia tylko
**kto** i **jak długo** czeka. Przy wywołaniach minutowych to zamienia się w
pracę zmarnowaną: klient rezygnuje po kilku minutach, a system i tak wykonuje
jego żądanie albo porzuca je w połowie. Odrzucenie po 1 ms jest dla klienta
(i dla Ciebie) lepszą odpowiedzią niż 504 po 6 minutach.

**Częsta pomyłka.** „Kolejka to bufor — wygładzi szczyt”. Wygładzi **krótki**
szczyt, gdy średnie λ < X_max. Przy trwałym przeciążeniu kolejka tylko odracza
porażkę i dokłada latencję wszystkim, także tym, których można było obsłużyć.

---

## Kolejka ograniczona i jej rozmiar

**Definicja.** **Kolejka ograniczona** ma maksymalną długość *K*; żądanie,
które przychodzi do pełnej kolejki, dostaje od razu odmowę. Rozmiar *K* wynika
z Little'a: żądanie na końcu kolejki czeka około **K / X_max**, więc
**K ≈ akceptowalne czekanie × X_max**.

**Intuicja.** Poczekalnia z określoną liczbą krzeseł. Jeśli wiesz, że lekarz
przyjmuje 4 osoby na godzinę, a nikt nie chce czekać dłużej niż 2 godziny —
stawiasz 8 krzeseł.

**Po co to.** Rozwiązanie ćw. 12 ma kolejki 64 (krótkie) i 8 (długie):
- krótkie: 64 / 30 na s ≈ **2.1 s** czekania na końcu kolejki przy pojemności
  32 slotów (30/s);
- długie: 8 / 0.105 na s ≈ **76 s** przy 16 slotach dla analiz trwających
  ~153 s (16 / 153 ≈ 0.105/s).

Dla długich pół minuty czekania w kolejce nie ma znaczenia przy kilku minutach
obsługi; dla krótkich 2 s to już dużo. Rozmiar kolejki to decyzja o SLO, nie
o pamięci.

**Częsta pomyłka.** Limit kolejki bez limitu **czasu** czekania. Kolejka 8
może się nie przepełnić, a mimo to żądania czekają długo, bo wszystkie sloty
trzymają wielominutowe wywołania. Dlatego obok długości jest **budżet
czekania** (niżej).

---

## Odrzucanie: 503, Retry-After i budżet czekania

**Definicja.** Odmowa ma być **szybka i czytelna**: status **503 Service
Unavailable** (albo 429, gdy limit dotyczy konkretnego klienta) z nagłówkiem
**`Retry-After`** — po ilu sekundach warto spróbować ponownie. W rozwiązaniu
ćw. 12 odmowa pada w dwóch miejscach:
- **przy wejściu** — kolejka klasy pełna (`kolejka_pelna`), `Retry-After` =
  budżet czekania klasy;
- **po budżecie czekania** — żądanie, które nie dostało slotu w ciągu 5 s
  (krótkie) / 20 s (długie), zostaje wyjęte z kolejki z 503 zamiast czekać
  dalej.

Wynik `odrzucone` jest liczony osobno w `app_requests_total{wynik}`.

**Intuicja.** „Proszę zadzwonić za 20 minut” jest lepsze niż trzymanie
dzwoniącego na linii przez godzinę z muzyczką — dzwoniący wie, co zrobić,
a linia jest wolna dla kogoś, kogo da się obsłużyć teraz.

**Po co to.** Ćw. 12, ruch mieszany 180 s (krótkie 4/s, długie 0.4/s), osobne
pule 32 / 16 już naprawione (wariant C → B):
- **bez limitu kolejki i budżetu (C)**: długie czekają p50 88 s / p99 272 s, w
  t = 180 s czeka 46 długich (najstarsze 115 s), **30 klientów porzuca żądanie**
  po 400 s (timeout k6) — 30 generacji anulowanych po minutach pracy; drain
  402 s;
- **z kolejką 8 i budżetem 20 s (B)**: **42 szybkie 503**, czekanie długich
  p99 19.4 s, 8 czeka w t = 180 s, drain 213 s.

Liczba ukończonych długich spadła (43 → 30) — i to jest **poprawne**: moc dla
długich (~0.1/s) jest czterokrotnie mniejsza niż dopływ (0.4/s). Bez odrzucania
system i tak nie zrobiłby więcej, tylko wydłużył czekanie wszystkim i zmarnował
pracę na porzucone żądania. Docelowo długie powinny trafić do kolejki zadań
(czytanka 14a).

**Częsta pomyłka.** Klient, który na 503 odpowiada natychmiastowym
ponowieniem — odmowa zamienia się w burzę ponowień (czytanka 08a). `Retry-After`
działa tylko wtedy, gdy klienci go honorują; w Twoich własnych klientach
(innych serwisach, workerach) to obowiązek. Druga pomyłka: odrzucanie
mierzone tak, że zawyża błędy — szybkie 503 to **zdrowe** zachowanie pod
przeciążeniem, a nie awaria; raportuj je osobno od 504 i 5xx.

---

## Deadline i jego propagacja

**Definicja.** **Deadline** to bezwzględna chwila, po której wynik nie ma już
wartości dla klienta. W odróżnieniu od timeoutu (ile czekać na jedną operację)
deadline obejmuje **całość**: czekanie w kolejce, wywołanie, ponowienia.
**Propagacja deadline'u** — każda warstwa wie, ile czasu zostało, i:
- nie zaczyna pracy, która nie zdąży (np. nie wywołuje LLM, jeśli żądanie
  przeczekało już większość budżetu w kolejce),
- przekazuje pozostały czas dalej (do wywołań podrzędnych, jako timeout).

**Intuicja.** Pociąg odjeżdża o 18:00. Jeśli o 17:55 stoisz w kolejce do kasy,
a sprzedaż biletu trwa 10 minut — nie ma sensu stać dalej. Kasjer, który wie,
o której odjeżdża Twój pociąg, odeśle Cię od razu.

**Po co to.** W kursie budżet czekania (ćw. 12: 5 s / 20 s) i deadline
wywołania (ćw. 10: krótkie 30 s, długie 330 s, `asyncio.timeout`) to dwie
części tego samego budżetu żądania. Bez nich żądanie potrafi czekać minutami
w kolejce, a potem i tak zająć slot u dostawcy na kolejne minuty — dla
klienta, który dawno się rozłączył.

**Częsta pomyłka.** Wspólny deadline dla wszystkich klas. 150 s „ratuje”
krótkie, ale zabija każdą analizę trwającą 200 s (test z budowy kursu: 7 / 7
długich strumieni przeterminowanych). Deadline ma odpowiadać **klasie**
żądania.

---

## Anulowanie po rozłączeniu i zwolnienie slotu

**Definicja.** Gdy klient się rozłączy (zamknął kartę, timeout k6, proxy
przerwało połączenie), serwer powinien **anulować** pracę wykonywaną dla
niego: zadanie asyncio dostaje `CancelledError`, połączenie z dostawcą się
zamyka, dostawca przerywa generację, slot semafora i slot u dostawcy wracają
od razu. Serwer dowiaduje się o rozłączeniu przez ASGI (zdarzenie
`http.disconnect`, w Starlette `await request.is_disconnected()`).

Dwie pułapki zmierzone przy budowie kursu:
- **Starlette 1.10 przy ASGI spec ≥ 2.4 nie nasłuchuje rozłączenia w
  `StreamingResponse`** — aplikacja musi sama sprawdzać
  `request.is_disconnected()` (w kursie: strażnik co 0.5 s obok wywołania LLM,
  sprawdzanie co kilka fragmentów w strumieniu);
- **`@app.middleware("http")` (BaseHTTPMiddleware) psuje
  `request.is_disconnected()`** w handlerach — z nim anulowanie nie działało
  wcale (6 / 6 generacji dokończonych „do nikogo”). Middleware aplikacji kursu
  jest napisane jako czyste ASGI.

**Intuicja.** Klient restauracji wyszedł, zanim podano danie. Dobra kuchnia
przestaje gotować i oddaje stolik następnym; zła gotuje do końca, a stolik
stoi zajęty z talerzem dla nikogo.

**Po co to.** Przy wywołaniach minutowych to różnica rzędu minut na każdym
porzuconym żądaniu. Ćw. 10: 6 analiz po 150 s generacji, klient rezygnuje po
20 s:
- bez anulowania: dostawca generuje dalej, sloty wolne dopiero **172.9 s** po
  rozłączeniu, 18 porzuconych generacji (każda 3 ×, bo SDK ponawiał timeouty);
- z anulowaniem: sloty wolne po **0.7 s**, 6 generacji anulowanych.

W finale (4 wady naraz) brak anulowania widać jako `mock_llm_cancelled_total` =
0 przy porzucających klientach i drain **125 s** po końcu ruchu (z anulowaniem:
24 anulowane, drain 32 s).

**Częsta pomyłka.** „Klient się rozłączył, więc serwer przestał pracować”.
Domyślnie nie: korutyna dalej czeka na dostawcę, a dostawca dalej generuje.
Sprawdzenie: po przerwaniu testu `llm_inflight` i `mock_llm_generating` muszą
spaść do zera w sekundach, a `mock_llm_cancelled_total` wzrosnąć.

---

## Streaming SSE

**Definicja.** **Server-Sent Events** (SSE) to strumień zdarzeń tekstowych
w jednej odpowiedzi HTTP (`Content-Type: text/event-stream`): każde zdarzenie
to linie `event: …` i `data: …` zakończone pustą linią. Dostawca LLM wysyła
nim odpowiedź kawałkami w miarę generacji (zdarzenia początku wiadomości,
fragmentów treści, `ping`, końca). Aplikacja kursu przekazuje strumień dalej
do klienta (`/reply/stream`: zdarzenia `delta` z fragmentami tekstu i `koniec`
z czasami).

**Intuicja.** Transmisja meczu na żywo zamiast nagrania udostępnionego po
końcowym gwizdku — widz widzi akcję od pierwszej minuty, choć mecz trwa tyle
samo.

**Po co to.** Trzy korzyści, każda ważna pod obciążeniem:
1. **Odczuwany czas** — użytkownik widzi pierwsze słowa po TTFT (~0.5 s), nie
   po całej generacji (kilka sekund — albo minut).
2. **Semantyka timeoutów** — read timeout pilnuje przerw między zdarzeniami,
   a nie całości (czytanka 08a); wielominutowa odpowiedź nie wymaga
   10-minutowego read.
3. **Wczesne wykrycie rozłączenia** — przy każdym fragmencie można sprawdzić,
   czy klient jest jeszcze po drugiej stronie.

**Częsta pomyłka.** „Streaming jest szybszy”. Czas całkowity jest taki sam
(TTFT + tokeny / tempo); zmienia się czas do **pierwszego** fragmentu i to,
jak system reaguje na ciszę i rozłączenia.

---

## TTFT serwera vs TTFT klienta i buforowanie

**Definicja.** Na ścieżce strumienia są co najmniej trzy różne „czasy do
pierwszego tokenu”:
- **TTFT u dostawcy / po stronie aplikacji** — od wysłania żądania do
  pierwszego fragmentu od dostawcy (`llm_ttft_seconds`);
- **pierwszy fragment wysłany klientowi** — od przyjęcia żądania przez
  aplikację do wysłania pierwszego `delta` (`app_stream_first_chunk_seconds`);
- **TTFT klienta** — od wysłania żądania do odebrania pierwszego fragmentu
  (mierzony po stronie klienta, w kursie `scripts/strumien_ttft.py`).

**Buforowanie strumienia** to sytuacja, w której ktoś po drodze zbiera
fragmenty i wysyła je dopiero na końcu (albo w dużych porcjach): aplikacja
składająca cały tekst przed pierwszym `yield`, warstwa kompresji, proxy
buforujące odpowiedzi. TTFT dostawcy jest wtedy w porządku, a klient i tak
czeka na całość.

**Intuicja.** Paczka wysłana ekspresem, która leży w sortowni do końca dnia,
bo kurier rozwozi tylko pełne auto. Nadawca wysłał szybko, odbiorca dostał
późno — każdy mierzy co innego.

**Po co to.** Ćw. 13: 20 strumieni po 5 naraz — z buforowaniem pierwszy
fragment u klienta p50 **2.19 s = 100%** całości, po naprawie (`yield` każdego
fragmentu) **0.55 s = 19%** całości (2.89 s). W finale: pierwszy fragment do
klienta p50 **8.07 s** przy TTFT dostawcy 0.63 s — różnica to jednoznaczny
sygnał buforowania (bez wady: 0.48 s vs 0.48 s).

**Częsta pomyłka.** Zaufanie metryce czasu z generatora ruchu. W k6
`http_req_waiting` przy SSE to czas **do nagłówków** — a `StreamingResponse`
wysyła nagłówki od razu, zanim powstanie pierwszy fragment. Buforowanie jest
dla tej metryki niewidoczne. Porównuj `app_stream_first_chunk_seconds` z
`llm_ttft_seconds` albo mierz klientem, który czyta strumień.

---

## Jak to się łączy (mapa)

```
 przybycie ──► kolejka ograniczona per klasa (64 / 8)  ── pełna ──► 503 + Retry-After (szybko)  [ćw. 12]
                 │ budżet czekania (5 s / 20 s)        ── przekroczony ──► 503
                 ▼
              slot (osobne pule 32 / 16) ──► deadline per klasa (30 s / 330 s)              [ćw. 10]
                 │                              └─ strażnik rozłączenia ──► anuluj: slot wraca w < 1 s
                 ▼                                 (Starlette: is_disconnected() samemu; bez BaseHTTPMiddleware)
              strumień SSE od dostawcy ── TTFT dostawcy (llm_ttft_seconds)
                 ▼   yield każdego fragmentu (bez buforowania)                              [ćw. 13]
              klient ── pierwszy fragment (app_stream_first_chunk_seconds, strumien_ttft.py)
                        k6 http_req_waiting = nagłówki → buforowania NIE widzi
 K ≈ akceptowalne czekanie × X_max;  nadmiar trwały → odrzucać albo do kolejki zadań (czytanka 14a)
```

Teraz przejdź do ćw. 12.
