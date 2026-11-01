# 14a. Czytanka: kolejki zadań, cache i batching

Czytanka, nie ćwiczenie — bez zadań i kryteriów „done”. Cel: zrozumieć trzy
techniki, które **zmieniają kształt ruchu** do dostawcy LLM, zanim w bloku V
zobaczysz ich wady: kolejka zadań (przesuwa pracę w czasie), cache (usuwa
część pracy), batching (skleja pracę w większe porcje). Każda z nich ma swój
rachunek w kategoriach L = λW i każda potrafi ukryć problem zamiast go
rozwiązać. Każde pojęcie w schemacie:

> **Definicja** → **Intuicja/analogia** → **Po co to** → **Częsta pomyłka**

Wracaj tu, gdy coś przestanie się spinać. Krótkie definicje są w `slownik.md`.

---

## Kolejka zadań: producent, broker, worker

**Definicja.** **Kolejka zadań** rozdziela przyjęcie pracy od jej wykonania.
**Producent** (aplikacja) zapisuje zadanie w **brokerze** i od razu odpowiada
klientowi identyfikatorem; **worker** (osobny proces) pobiera zadania i
wykonuje je we własnym tempie; wynik trafia do **backendu wyników**, skąd
klient go odbiera. W kursie: **taskiq** + **Redis Streams** — endpoint
`POST /claims/{n}/summary/async` zleca streszczenie, `GET /jobs/{id}` zwraca
wynik (przechowywany 1 h); worker uruchamiasz poleceniem
`taskiq worker app.zadania:broker --workers 2 --max-async-tasks 4`.

Redis Streams to dziennik wpisów (`XADD` dopisuje), z którego **grupa
konsumentów** czyta wpisy nowe dla grupy (`XREADGROUP`) i potwierdza wykonanie
(`XACK`). Zadania taskiq są `async def` — worker to pętla asyncio, jak
aplikacja, więc współbieżność opisują te same pojęcia: sloty, Little,
limit dostawcy.

**Intuicja.** Pralnia: oddajesz worek przy ladzie i dostajesz kwit (producent
→ broker → identyfikator). Pralki (workery) piorą w swoim tempie; po pranie
wracasz z kwitem (backend wyników). Kolejka worków jest widoczna na zapleczu —
o ile ktoś ją liczy.

**Po co to.** Kolejka zadań to naturalne miejsce dla wywołań **wielominutowych**
i dla ruchu, który przekracza pojemność tylko chwilowo: klient nie trzyma
połączenia HTTP przez minuty, aplikacja nie trzyma slotu, a nadmiar czeka w
brokerze zamiast w pamięci procesu. Pojemność workera liczysz z Little'a:
**L = workers × max-async-tasks**, przepustowość X = L / W. Pomiar z kursu:
2 × 4 = 8 równoległych zadań, 200 zadań w 28.7 s → X ≈ 7.0/s → W ≈ 8 / 7.0 ≈
1.15 s na zadanie.

**Częsta pomyłka.** „Kolejka zadań rozwiązuje problem pojemności”. Nie: przy
trwałym λ > X zaległość w brokerze rośnie bez końca dokładnie tak, jak rosła
w pamięci aplikacji. Zyskujesz **widoczność i trwałość** zaległości oraz
oddzielenie jej od żądań HTTP — nie dodatkową moc. Potrzebujesz metryk
kolejki (niżej) i decyzji, co robić, gdy zaległość jest za duża.

---

## Współbieżność workera a limit dostawcy

**Definicja.** Współbieżność workera taskiq to iloczyn **`--workers`** (procesy)
× **`--max-async-tasks`** (zadania naraz w procesie). To **zamknięta** pula —
dokładnie jak model zamknięty generatora ruchu: worker nie pobierze nowego
zadania, dopóki nie skończy któregoś z bieżących (o ile nie ma prefetchu —
niżej).

**Intuicja.** Liczba pralek. Dziesięć pralek przy jednym przyłączu wody, które
wystarcza dla czterech, nie pierze szybciej — pralki stają z błędem.

**Po co to.** Domyślnie taskiq uruchamia **2 procesy × 100** zadań naraz.
Dostawca w profilu `przeciazenie` ma moc 8 generacji + kolejkę 8, powyżej —
529. Ćw. 14, 200 zadań: przy 2 × 100 **179 / 200 kończy się błędem** w 6 s
(220 × 529); przy **2 × 4 = 8** (moc dostawcy) — 200 / 200 w 28.7 s, 0 × 529.
Współbieżność workera dobierasz do pojemności tego, co jest za nim, a nie do
długości kolejki przed nim.

**Częsta pomyłka.** „Kolejka rośnie, dodajmy współbieżności”. Jeśli wąskim
gardłem jest dostawca, większa współbieżność zamienia zaległość w kolejce
(niegroźną, widoczną) w błędy i ponowienia (groźne, mnożące ruch).

---

## Metryki kolejki: lag ≠ XLEN, pending, wiek najstarszego

**Definicja.** Dla Redis Streams z grupą konsumentów:
- **`XLEN`** — liczba wpisów w strumieniu. taskiq **nie usuwa** wpisów po
  wykonaniu, więc XLEN rośnie z każdym zadaniem i **nie** jest długością
  kolejki (w teście z budowy kursu: XLEN = 120 po przetworzeniu wszystkich 120
  zadań);
- **lag** (`XINFO GROUPS`) — liczba wpisów jeszcze **nieodebranych** przez
  grupę — prawdziwa długość kolejki;
- **pending** (`XPENDING`) — wpisy **odebrane, ale niepotwierdzone**: w toku
  plus pobrane na zapas;
- **wiek najstarszego** — ile czeka najstarsze nieodebrane zadanie (ID wpisu w
  Redis Streams zawiera znacznik czasu w milisekundach, więc wiek liczy się z
  ID pierwszego wpisu po `last-delivered-id` grupy).

Eksporter kursu (port 8063) wystawia je jako `kolejka_xlen` (celowo — jako
pułapka), `kolejka_lag`, `kolejka_pending`, `kolejka_wiek_najstarszego_s` i
`kolejka_wiek_najstarszego_pending_s`.

**Intuicja.** XLEN to numer ostatniego wydanego kwitu w pralni — rośnie
zawsze, nawet gdy wszystko wyprane. Lag to worki na zapleczu, których nikt
jeszcze nie dotknął. Pending to worki w pralkach i te, które pracownik
odłożył „dla siebie” przy swojej pralce. Wiek najstarszego — od kiedy leży
najstarszy worek.

**Po co to.** **Wiek najstarszego** to najlepszy pojedynczy sygnał SLO kolejki:
długość mówi, ile jest pracy, wiek — jak długo klient czeka. Przy zadaniach
różnej długości ta sama długość kolejki oznacza zupełnie inne czekanie
(10 streszczeń po 1 s vs 10 analiz po 150 s). Alarmuj na wiek, nie na długość.

**Częsta pomyłka.** Alarm na `XLEN` — rośnie monotonicznie, więc albo dzwoni
zawsze, albo ktoś podniesie próg tak, że nie zadzwoni nigdy.

---

## Prefetch ukrywa kolejkę

**Definicja.** **Prefetch** — worker pobiera z brokera więcej zadań, niż
akurat wykonuje, „na zapas”, żeby nie czekać na sieć przy następnym. W
taskiq-redis to parametr `xread_count`. Pobrane zadania przestają być
„w kolejce” (lag maleje), choć nikt ich jeszcze nie wykonuje — leżą w pamięci
jednego procesu jako pending.

**Intuicja.** Pracownik pralni, który zabiera z zaplecza 100 worków i
ustawia je przy swojej pralce. Zaplecze wygląda na puste, kolega obok stoi
bezczynnie, a klienci czekają tak samo.

**Po co to.** Ćw. 14 (W15): przy prefetchu 100 lag przez cały test wynosił
**0** — kolejka „pusta”, choć zadania czekały (i kończyły się błędami). Po
ustawieniu prefetchu równego `max-async-tasks` (4): lag max **190** →
spada do 0 w tempie ~7/s — kolejka stała się widoczna i opróżniana zgodnie
z rachunkiem. Prefetch zawłaszcza też pracę: jeden proces może zabrać
zadania, które drugi zrobiłby od razu.

**Częsta pomyłka.** Patrzenie na lag bez pending. Zdrowa kolejka to lag
malejący i **pending ≈ współbieżność**; pending ≫ współbieżność znaczy, że
zadania czekają po stronie workera, poza metryką lagu.

---

## Cache odpowiedzi

**Definicja.** **Cache** przechowuje wynik wywołania pod kluczem (w kursie:
skrót znormalizowanego pytania FAQ) przez czas **TTL**. Trafienie (*hit*) nie
woła LLM; chybienie (*miss*) woła i zapisuje. **Współczynnik trafień** *h*
zmniejsza ruch do dostawcy: λ_dostawca = (1 − h) · λ. Aplikacja liczy wyniki w
`app_cache_total{wynik="hit"|"miss"|"wspolne"}`.

**Intuicja.** Tablica „najczęstsze pytania” przy okienku: na pytanie
„do kiedy zgłosić szkodę?” odpowiada tablica, a nie urzędnik.

**Po co to.** Dla pytań powtarzalnych (FAQ, szablony) cache obniża i koszt, i
obciążenie limitów — przy idealnym single-flight liczba wywołań LLM to
**liczba różnych kluczy × (czas / TTL)**, niezależnie od ruchu. W finale: 5
pytań × 240 s / TTL 30 s ≈ **40** potrzebnych wywołań (zmierzone po
naprawie: 36).

**Częsta pomyłka.** Cache odpowiedzi LLM tam, gdzie odpowiedź zależy od
kontekstu (konkretne zgłoszenie, klient, historia) — trafienia będą rzadkie,
a każde trafienie może być błędne. Cache ma sens dla danych, w których to samo
pytanie ma mieć tę samą odpowiedź.

---

## Cache stampede i single-flight

**Definicja.** **Cache stampede** (lawina) — klucz wygasa (albo go jeszcze nie
ma), a N równoczesnych żądań o ten sam klucz widzi chybienie i **każde** woła
LLM: N wywołań zamiast jednego, falą co TTL. **Single-flight** — tylko
pierwsze żądanie liczy wynik, pozostałe **czekają na jego wynik** (w procesie:
wspólny `asyncio.Future` per klucz; między procesami: blokada w Redisie
`SET klucz NX PX czas`, w rozwiązaniu kursu 30 s — dłużej niż deadline
krótkich).

**Intuicja.** Na wiadomość „skończyła się kawa” dziesięć osób naraz idzie do
sklepu. Single-flight: jedna idzie, reszta czeka na nią przy ekspresie.

**Po co to.** Ćw. 15: 50 równoczesnych identycznych pytań — **50** wywołań
LLM, p99 4.6 s → po single-flight **1** wywołanie (49 „wspólne”), p99 1.32 s.
W finale stampede wzmacnia się z innymi wadami: przy 4 slotach (za mała pula)
żądanie liczące wynik dłużej czeka na slot, więc okno „miss” trwa dłużej i
chybień jest **290** zamiast ~40. Kolejka przed LLM wydłuża stampede — dwie
wady mnożą się zamiast dodawać.

**Częsta pomyłka.** Single-flight bez limitu czasu. Gdy jedyne liczące żądanie
zawiśnie albo zostanie anulowane, wszyscy czekający wiszą razem z nim —
blokada musi wygasać, a błąd lidera musi trafić do czekających (albo jeden z
nich przejmuje liczenie).

---

## Batching: okno i rozmiar

**Definicja.** **Batching** (przetwarzanie wsadowe) skleja wiele małych próśb
w jedno wywołanie LLM (w kursie: ocena priorytetu wielu zgłoszeń jednym
wywołaniem, endpoint `POST /claims/{n}/priority`). Dwa parametry:
- **okno** — jak długo czekać na skompletowanie wsadu;
- **maksymalny rozmiar** — ile próśb najwyżej w jednym wsadzie.

Wsad wysyła się, gdy minie okno **albo** wsad się zapełni. Średni rozmiar
wsadu ≈ **min(λ × okno, max)**; dodatkowa latencja pojedynczej prośby ≤ okno.
Aplikacja raportuje rozmiar w `app_batch_size_bucket`.

**Intuicja.** Bus wahadłowy na lotnisku: odjeżdża co 10 minut albo gdy się
zapełni. Przy małym ruchu jedziesz sam, ale po 10 minutach czekania; przy
dużym — szybko, w pełnym busie. Zbyt duży bus jedzie dłużej (więcej
przystanków), a gdy się zepsuje, utyka cały.

**Po co to.** Batching zmniejsza liczbę **żądań** do dostawcy (limit RPM,
narzut per wywołanie), ale nie zmniejsza liczby **tokenów** do przetworzenia
(ITPM/OTPM) — i wydłuża czas pojedynczego wywołania. Ćw. 16, okno 2 s i wsad
do 100 (szkielet):
- pojedyncza prośba przy małym ruchu: **2.78 s** (czeka całe okno);
- 30 próśb/s: 30 × 2 s ≈ **60** próśb we wsadzie, 5 wywołań, p99 4.5 s.

Po zmianie na okno 50 ms i wsad ≤ 16: pojedyncza **0.54 s**; przy 30/s wsady
p50 2 (30 × 0.05 ≈ 1.5), max 5, 146 wywołań, p99 1.14 s. Wywołań jest więcej,
ale każde krótkie, a ogon zniknął.

**Częsta pomyłka.** Dobór okna i rozmiaru pod przepustowość bez patrzenia na
limity tokenów. Wsad 100 zgłoszeń po ~80 tokenów to 8 000 tokenów wejścia w
jednym żądaniu: przy ITPM 60 000 (profil `limity`) zmieszczą się 7.5 takich
wsadów na minutę, a jedno 429 odrzuca **cały** wsad — 100 próśb naraz. Wsad
≤ 16 to ~1 280 tokenów wejścia: błąd dotyka mniej próśb, a limit tokenów jest
konsumowany równiej.

---

## Jak to się łączy (mapa)

```
            ┌─ cache (TTL, klucz) ── hit ──► odpowiedź bez LLM: λ_dostawca = (1−h)·λ        [ćw. 15]
 żądanie ───┤    miss ──► single-flight (Future w procesie + SET NX PX między procesami)
            │              (bez niego: N chybień → N wywołań; dłuższe czekanie na slot = większy stampede)
            ├─ batching: okno ∧ rozmiar → wsad ≈ min(λ·okno, max); +≤ okno latencji;            [ćw. 16]
            │              mniej żądań (RPM), tyle samo tokenów (ITPM/OTPM), 429 = cały wsad
            └─ kolejka zadań (taskiq + Redis Streams) → worker: L = workers × max-async-tasks   [ćw. 14]
                   metryki: lag (prawdziwa kolejka) · pending (≈ współbieżność) · wiek najstarszego (SLO)
                   pułapki: XLEN ≠ kolejka · prefetch ≫ współbieżność ukrywa kolejkę · L > moc dostawcy = 529
```

Teraz przejdź do ćw. 14.
