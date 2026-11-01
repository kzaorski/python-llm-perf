# 04a. Czytanka: asyncio, pętla zdarzeń i pule — od strony systemu pod obciążeniem

Czytanka, nie ćwiczenie — bez zadań i kryteriów „done”. Cel: zrozumieć model
współbieżności aplikacji (jedna pętla zdarzeń, korutyny, pula wątków, semafor,
pula połączeń, procesy) jako **zestaw stacji obsługi z limitami** — zanim w
blokach II zaczniesz je zatykać i odtykać. Podstawy asyncio są tu wyłożone od
zera, ale z naciskiem na to, co dzieje się z kolejkami i przepustowością pod
ruchem, nie na mikroskopię pojedynczego procesu. Każde pojęcie w schemacie:

> **Definicja** → **Intuicja/analogia** → **Po co to** → **Częsta pomyłka**

Wracaj tu, gdy coś przestanie się spinać. Krótkie definicje są w `slownik.md`.

---

## Pętla zdarzeń

**Definicja.** **Pętla zdarzeń** (*event loop*) asyncio to jeden wątek, który w
kółko: (1) pyta system operacyjny, które gniazda mają dane albo są gotowe do
zapisu (selektor: `kqueue` na macOS, `epoll` na Linuksie), (2) budzi korutyny,
które na te zdarzenia czekały, (3) wykonuje każdą z nich **do najbliższego
`await`**, (4) wraca do kroku 1. Wszystkie żądania obsługiwane przez proces
uvicorna dzielą tę jedną pętlę i ten jeden wątek.

**Intuicja.** Kelner, który obsługuje 50 stolików: przyjmuje zamówienie, zanosi
do kuchni i **nie stoi przy okienku**, tylko idzie do następnego stolika; wraca,
gdy kuchnia zadzwoni. Jeden kelner wystarczy, dopóki żadna czynność nie
wymaga, żeby stał w miejscu. Jeśli jeden stolik każe mu czekać przy sobie
2 minuty — 49 pozostałych czeka razem z nim.

**Po co to.** Aplikacja LLM spędza prawie cały czas na czekaniu na sieć — a
czekanie w asyncio nic nie kosztuje: tysiąc korutyn czekających na dostawcę to
tysiąc małych obiektów w pamięci i jeden wątek. Dlatego jeden proces uvicorna
obsługuje dziesiątki równoległych wywołań LLM. Ale pętla jest **stacją z
jednym serwerem** (c = 1) dla całego kodu wykonywanego między `await`ami: jeśli
ten kod trwa długo, rośnie kolejka gotowych korutyn i każda — także `/health` —
czeka.

**Częsta pomyłka.** „Async znaczy równolegle”. Nie: korutyny wykonują się
**na zmianę** w jednym wątku. Równolegle (w sensie „w tym samym czasie”)
dzieje się tylko czekanie — na sieć, na dysk, na timer. Obliczenia w Pythonie
i tak są ograniczone GIL-em, a w pętli zdarzeń — jej jedynym wątkiem.

---

## Korutyna, `await`, zadanie

**Definicja.**
- **Korutyna** — funkcja `async def`; wywołana zwraca obiekt korutyny, który
  wykonuje się dopiero, gdy ktoś go `await`uje albo opakuje w zadanie.
- **`await x`** — „zawieś mnie, aż `x` będzie gotowe”; oddaje sterowanie pętli.
  To jedyne miejsce, w którym inna korutyna może dostać czas.
- **Zadanie** (`asyncio.Task`) — korutyna zaplanowana w pętli, wykonująca się
  niezależnie (np. każde żądanie HTTP w uvicornie to osobne zadanie). Zadanie
  można **anulować** (`task.cancel()`): w miejscu, w którym czeka, dostaje
  wyjątek `CancelledError`.

**Intuicja.** Zakładka w książce. `await` to włożenie zakładki i odłożenie
książki — kelner (pętla) może w tym czasie czytać inną. Anulowanie to
wyjęcie zakładki i zamknięcie książki: przy najbliższej okazji czytelnik
dowie się, że ma przestać.

**Po co to.** Dwie rzeczy ważne pod obciążeniem:
1. **Zawieszona korutyna nie zużywa wątku ani CPU** — dlatego jest niewidoczna
   w profilu, ale doskonale widoczna w trace (span trwa) i w metrykach
   (`llm_inflight`, `llm_waiting`).
2. **Anulowanie jest jedynym sposobem, żeby zwolnić zasoby trzymane przez
   czekające zadanie** — slot semafora, połączenie, generację u dostawcy.
   `asyncio.timeout(60)` (deadline całkowity) i strażnik rozłączenia klienta
   działają właśnie przez anulowanie (czytanki 08a i 12a, ćw. 10).

**Częsta pomyłka.** Wywołanie korutyny bez `await` („przecież wywołałem
funkcję”) — nic się nie wykona, a Python wypisze ostrzeżenie *coroutine was
never awaited*. Druga: łapanie `except Exception` wokół `await` z
przekonaniem, że to złapie anulowanie — `CancelledError` dziedziczy po
`BaseException`, a połknięcie go blokuje mechanizm deadline'ów.

---

## Blokada pętli

**Definicja.** **Blokada pętli** to wykonanie w korutynie kodu, który trwa
długo **bez `await`**: synchroniczne wywołanie sieciowe (`anthropic.Anthropic`,
`requests`, `time.sleep`), ciężkie obliczenia, synchroniczny odczyt dużego
pliku. Na ten czas pętla nie obsługuje nikogo. Miarą jest **lag pętli** —
opóźnienie, z jakim pętla wykonuje callback zaplanowany „za chwilę” (w
aplikacji: `app_event_loop_lag_seconds`, `petla_lag_max_10s_ms` w `/diag`).

**Intuicja.** Kelner, który osobiście czeka przy kuchni, aż danie będzie
gotowe. Restauracja obsługuje wtedy jeden stolik naraz — niezależnie od tego,
ile ma stolików i kucharzy.

**Po co to.** Skutek systemowy jest dużo poważniejszy niż „jedno wolne
żądanie”. W ćw. 4 synchroniczny klient LLM w handlerze `async def`:
- burst 20 klasyfikacji po 0.5 s trwa **10.55 s** = 20 × 0.5 s — szeregowo; lag
  pętli dochodzi do 6.6 s;
- ruch otwarty 6/s klasyfikacji + 2/s streszczeń: proces kończy **2.05/s**,
  p99 klasyfikacji 62 s, 22 ze 180 żądań zerwanych, `/diag/ping` (nic nie
  robi) czeka do 10.9 s, ostatnia odpowiedź przychodzi 88 s po starcie
  30-sekundowego testu;
- po naprawie (wywołanie async): 5.89/s, p99 1.0 s, ping p99 13 ms.

Z perspektywy teorii kolejek pętla stała się jednym serwerem o czasie obsługi
równym czasowi wywołania LLM — pojemność spada do 1 / 0.5 s = 2/s. Kolejka
rośnie w miejscach, których semafor nie widzi (czekanie na semaforze = 0): w
gnieździe i w pętli. Ucierpią wszystkie endpointy, także health-check —
orkiestrator kontenerów może zacząć restartować „martwy” proces.

**Częsta pomyłka.** Szukanie blokady wyłącznie w profilu CPU. Synchroniczny
klient czeka na gnieździe, więc w profilu CPU zajmuje ułamek procenta; w
profilu wall jest widoczny (`SyncStream.read`). Najszybszy dowód to jednak
objaw systemowy: osiągnięte tempo ≈ 1 / czas wywołania i lag pętli rzędu
sekund.

---

## `def` vs `async def` w FastAPI i pula wątków anyio

**Definicja.** FastAPI (przez Starlette i bibliotekę anyio) wykonuje handler
zdefiniowany jako zwykłe `def` **w puli wątków**, żeby nie blokował pętli. Tak
samo działa `run_in_threadpool` / `anyio.to_thread.run_sync`. Pula ma
domyślny **limiter na 40 równoczesnych wątków** (`total_tokens = 40`,
sprawdzone w anyio 4.15). Wywołanie ponad limit czeka na wolny token — bez
zużycia CPU, bez spanu, bez metryki.

**Intuicja.** Do kuchni prowadzi 40 par drzwi. Kelnerzy (wątki), którzy weszli
z zamówieniem synchronicznym, stoją w środku, dopóki danie nie będzie gotowe.
Czterdziesty pierwszy czeka pod drzwiami — choć w kuchni nikt nic nie robi,
wszyscy czekają na piec.

**Po co to.** Pula wątków to stacja o c = 40 i czasie obsługi równym **całemu**
synchronicznemu wywołaniu (z czekaniem na sieć). Ćw. 5: 60 równoczesnych pism
po ~2.1 s → ⌈60 / 40⌉ = 2 fale: 40 kończy się po 2.2 s, 20 — po 4.35 s (p99
4.36 s); po przepisaniu na `async def` z klientem async: jedna fala, p99
2.28 s. Pojemność puli dla takich wywołań: 40 / 2.1 s ≈ 19/s — przy minutowych
wywołaniach 40 / 150 s ≈ 0.27/s. Charakterystyczny objaw: czas odpowiedzi
rośnie **schodkami** co 40 żądań.

**Częsta pomyłka.** „Podnieśmy limiter do 1000”. Każdy wątek to pamięć (stos)
i walka o GIL; pula 1000 wątków czekających na sieć robi to, co jedna pętla
zrobiłaby za darmo. Drugi błąd: limit 40 jest **wspólny** dla całego procesu
— jeden wolny moduł synchroniczny zjada tokeny innym `def`-handlerom i
wszystkim `run_in_threadpool`.

---

## Semafor: jawny limit współbieżności

**Definicja.** `asyncio.Semaphore(n)` przepuszcza naraz co najwyżej *n*
korutyn; kolejne czekają (zawieszone) w jego wewnętrznej kolejce, aż ktoś
zwolni slot. W aplikacji kursu semafor LLM (moduł `app/llm/limiter.py`) to
**główny, jawny limit współbieżności wobec dostawcy**: ma osobne sloty dla
klas (krótkie / długie), mierzy czas czekania (span `llm.queue_wait`,
histogram `llm_queue_wait_seconds`) i wystawia zajętość (`llm_inflight`),
liczbę czekających (`llm_waiting`) i wiek najstarszego czekającego.

**Intuicja.** Bramka na parking z licznikiem wolnych miejsc. Kolejka przed
bramką jest widoczna — dlatego wolisz ją od niewidocznych kolejek w środku.

**Po co to.** Semafor zamienia ukryte kolejki (w puli połączeń, u dostawcy —
429/529) w **jedną kolejkę, którą widzisz i kontrolujesz**. Jego rozmiar
liczysz z Little'a: dla 20 streszczeń/s po 1.06 s potrzeba średnio 21 slotów;
4 sloty dają pojemność 3.77/s i przy 20/s czekanie p50 32 s (ćw. 6), 32 sloty —
czekanie p99 = 0. Do semafora dokładasz potem limit długości kolejki i budżet
czekania (ćw. 12).

**Częsta pomyłka.** Semafor bez pomiaru czekania. Jeśli span czekania jest
**rodzicem** wywołania (a nie rodzeństwem), czas wywołania wlicza się w
czekanie — wykres wygląda, jakby wszystko było kolejką. Drugi błąd: w kilku
procesach każdy ma **własny** semafor — globalny limit to procesy × sloty
(ćw. 7: `LLM_SLOTY` jest per proces).

---

## Pula połączeń httpx / httpx2

**Definicja.** Klient HTTP utrzymuje **pulę połączeń** TCP (z keep-alive) do
każdego hosta. `httpx.Limits` / `httpx2.Limits` określa
`max_connections` (ile naraz) i `max_keepalive_connections` (ile bezczynnych
trzymać). Domyślnie w httpx 0.28 i httpx2 2.16: **100 / 20**, timeout 5 s. SDK
`anthropic` 2.3 (stoi na httpx2) tworzy własnego klienta z limitem **1000
połączeń** i timeoutem **connect 5 s, read/write/pool 600 s**. Żądanie, które
nie dostało połączenia, czeka w puli do `pool` timeoutu, potem dostaje
`PoolTimeout` — w SDK widoczny jako `anthropic.APITimeoutError`.

**Intuicja.** Firma z flotą 8 samochodów. Kierowców (korutyn przepuszczonych
przez semafor) może być 64, ale jeździ naraz 8 — reszta siedzi w biurze z
kluczykami w ręku i liczy to sobie jako „czas jazdy”.

**Po co to.** Pula to druga stacja z limitem po semaforze. Jeśli jest
**mniejsza** niż semafor, staje się wąskim gardłem, którego nie widzisz w
spanie czekania. Wariant ćw. 6: semafor 64, pula 8 — u dostawcy najwyżej
**8** generacji naraz, „wywołanie LLM” p50 8.2 s przy 1-sekundowej generacji,
całość p99 24.7 s. Przy domyślnym `pool = 600 s` czekanie w puli jest ciche;
przy `pool = 5 s` (po ćw. 10) wychodzi na jaw: 86 / 300 żądań kończy się 504
(`APITimeoutError` z `PoolTimeout`) — a z włączonym fallbackiem 77 żądań po
cichu przechodzi do zapasowego dostawcy. Reguła: **jeden jawny limit**
(semafor) i pula ≥ semafor, albo pula jako limit, ale wtedy z mierzonym
czasem czekania.

**Częsta pomyłka.** Nowy klient HTTP (albo nowy `AsyncAnthropic`) na każde
żądanie „żeby było czysto” — każde wywołanie płaci zestawienie połączenia i
TLS, a limity puli przestają cokolwiek znaczyć. Klient jest **jeden na proces**
i żyje tyle, co aplikacja. Druga pomyłka: `except APIConnectionError` z myślą
o „zerwanych połączeniach” — `APITimeoutError` jest jego podklasą, więc ta
gałąź łapie też `PoolTimeout` i timeouty odczytu.

---

## Procesy: gunicorn sync vs UvicornWorker

**Definicja.** Jeden proces Pythona to jedna pętla (i jeden GIL). Żeby użyć
wielu rdzeni albo izolować awarie, uruchamia się kilka procesów pod
menedżerem — w kursie **gunicorn**:
- **`-k sync`** — każdy proces obsługuje **jedno żądanie naraz** (aplikacja
  WSGI). Popularna heurystyka liczby procesów **2 × CPU + 1** (na maszynie
  autora 29) pochodzi ze świata obciążeń CPU; przy I/O pojemność to
  procesy / czas wywołania. Domyślny `--timeout 30`: proces, który nie
  odpowiedział nadzorcy przez 30 s, zostaje zabity (`WORKER TIMEOUT`).
- **`-k uvicorn_worker.UvicornWorker`** (paczka `uvicorn-worker`) — każdy
  proces to pełna pętla asyncio z wieloma żądaniami naraz; współbieżność
  procesu wyznacza semafor (w kursie 32 sloty na proces). Timeout gunicorna
  dotyczy tu sygnału życia procesu, nie czasu żądania.

Żądania, których żaden proces nie przyjął, czekają w **backlogu gniazda**
(kolejka w jądrze); gdy się przepełni, klient dostaje zerwane połączenie.

**Intuicja.** `sync` to 29 kas, przy każdej kasjer, który po zeskanowaniu
towarów stoi i czeka, aż klient znajdzie portfel. UvicornWorker to dwie kasy
samoobsługowe z kasjerem, który pilnuje 32 klientów naraz.

**Po co to.** Ćw. 7, 15 żądań/s po ~3.5 s (L ≈ 52):
- `-k sync`, 29 procesów: pojemność 29 / 3.5 ≈ 8.3/s (zmierzone 9.05/s);
  p50 11.3 s, **63 / 450** połączeń zerwanych (backlog), **2111 MB** pamięci;
  pojedyncze żądanie 90 s → **500 po 30.3 s** (worker zabity);
- UvicornWorker × 2 (2 × 32 sloty ≈ 18/s pojemności): osiągnięte 13.0/s, 450 /
  450 OK, p50 3.9 s, **317 MB**; żądanie 90 s → **200 po 90.6 s**.

Przy wywołaniach 60–300 s `-k sync` jest nie do obrony: proces zajęty
minutami, timeout 30 s zabija go w trakcie, a podniesienie `--timeout`
tylko ukrywa, że pojemność to kilka żądań na minutę.

**Częsta pomyłka.** Mnożenie procesów bez przeliczenia globalnego limitu.
Dwa procesy po 32 sloty to 64 równoległe wywołania u dostawcy — jeśli jego
moc albo limit tokenów jest mniejszy, dodatkowy proces dokłada tylko 429/529.
Liczba procesów wynika z CPU i odporności na awarię; współbieżność wobec
dostawcy — z jego limitów.

---

## GIL w jednym akapicie

**Definicja.** **GIL** (*global interpreter lock*) w CPython pozwala tylko
jednemu wątkowi naraz wykonywać kod Pythona. Wątek czekający na I/O
(gniazdo, `sleep`) zwalnia GIL.

**Intuicja.** Jeden mikrofon na sali — mówi tylko ten, kto go trzyma; kto
czeka na odpowiedź z sieci, odkłada mikrofon.

**Po co to.** Dla aplikacji I/O-bound GIL prawie nie ma znaczenia: wątki z
puli i pętla i tak głównie czekają. Ma znaczenie, gdy obok czekania pojawia się
CPU (parsowanie dużych odpowiedzi, tokenizacja, serializacja) — wtedy wątki i
pętla walczą o jeden „mikrofon”, a lag pętli rośnie.

**Częsta pomyłka.** Dokładanie wątków na problem, który jest kolejką na
semaforze albo limitem dostawcy. Wątki nie zwiększają pojemności stacji, która
jest za nimi.

---

## Jak to się łączy (mapa)

```
 gunicorn (procesy) ── backlog gniazda (jądro) ──┐                        [ćw. 7]
   -k sync: 1 żądanie/proces, timeout 30 s        │
   UvicornWorker: pętla + 32 sloty/proces         ▼
                         ┌── pętla zdarzeń (1 wątek, c = 1 dla kodu między await) ── lag pętli [ćw. 4]
                         │      ├─ `def` / run_in_threadpool ──► anyio: 40 wątków (fale co 40) [ćw. 5]
                         │      ▼
                         │   semafor LLM (sloty per klasa, czekanie mierzone)         [ćw. 1, 6, 12]
                         │      ▼
                         │   pula httpx2 (SDK: 1000; pool timeout 600 s → czekanie ukryte) [ćw. 6]
                         │      ▼
                         └── await na dostawcę: korutyna zawieszona — trace TAK, profil NIE
 globalna współbieżność wobec dostawcy = procesy × sloty  ≤  jego moc i limity (czytanka 08a)
```

Teraz przejdź do ćw. 4.
