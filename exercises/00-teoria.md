# 00. Teoria: aplikacja LLM pod obciążeniem — czekanie, kolejki, pojemność

Duży primer, nie ćwiczenie — bez zadań i kryteriów „done”. Cel: zbudować mapę
pojęć, zanim wejdziesz w ćwiczenia 1–18. Każde pojęcie w schemacie:

> **Definicja** → **Intuicja/analogia** → **Po co to** → **Częsta pomyłka**

Wracaj tu, gdy coś przestanie się spinać. Krótkie definicje wszystkich terminów
są w `slownik.md`. Przed blokami tematycznymi czekają węższe czytanki:
`01a-teoria-kolejek-w-praktyce.md`, `04a-asyncio-petla-i-pule.md`,
`08a-limity-retry-timeouty.md`, `12a-backpressure-i-streaming.md`,
`14a-kolejki-zadan-cache-batching.md`. Ten dokument daje wspólny fundament pod
wszystkie pięć.

Kontekst: przez cały kurs diagnozujesz jedną aplikację — **asystenta biura
obsługi zgłoszeń szkodowych** (ubezpieczenia). To serwis FastAPI na asyncio,
który dla każdego zgłoszenia woła model językowy: streszcza zgłoszenie,
klasyfikuje je, pisze odpowiedź do klienta, ocenia priorytet, robi
wielominutową analizę, odpowiada na częste pytania (FAQ). Prawie cały czas
życia żądania to **czekanie na LLM** — procesor aplikacji się nudzi, a mimo
to aplikacja potrafi się „zatkać”. Dostawcą LLM jest **atrapa** — własny
serwer zgodny z Messages API, z którym rozmawia oficjalny SDK `anthropic`;
ma powtarzalne rozkłady opóźnień, limity, błędy 429/529, streaming i profile
minutowe. W jednym ćwiczeniu porównasz ją z prawdziwym Claude.

Liczby w tym dokumencie zostały zmierzone w środowisku kursu (macOS + Docker
Desktop, Python 3.13, FastAPI 0.162, uvicorn 0.54, anthropic 2.3.0 na httpx2
2.16, k6 2.3, atrapa w kontenerze) albo wyprowadzone rachunkiem pokazanym w
tekście. Na innym sprzęcie będą inne — rzędy wielkości i kształty krzywych
zostają.

---

## Latencja, przepustowość, współbieżność

**Definicja.** Trzy wielkości, którymi opiszesz każdy system pod obciążeniem:
- **Latencja** (czas odpowiedzi, *R*) — ile trwa jedno żądanie od przybycia do
  ostatniego bajtu odpowiedzi. Mierzy ją klient (albo serwer — to dwie różne
  liczby, wrócimy do tego).
- **Przepustowość** (*X*) — ile żądań na sekundę system **kończy**. Nie: ile
  do niego **przychodzi** — to jest **intensywność dopływu** (*λ*). Dopóki
  system nadąża, X = λ; gdy nie nadąża, X zatrzymuje się na pojemności, a
  różnica λ − X ląduje w kolejce.
- **Współbieżność** (*L*) — ile żądań jest w systemie **naraz** (czekających
  i obsługiwanych). W asyncio to liczba żywych zadań, w puli — liczba zajętych
  slotów, u dostawcy — liczba trwających generacji.

**Intuicja.** Autostrada: latencja to czas przejazdu odcinka, przepustowość —
ile aut na minutę przejeżdża przez bramkę na końcu, współbieżność — ile aut
jest w tej chwili na odcinku. Korek to sytuacja, w której wjeżdża więcej, niż
wyjeżdża: przepustowość na bramce się nie zmienia, rośnie tylko liczba aut na
odcinku i czas przejazdu.

**Po co to.** Każde ćwiczenie kursu sprowadza się do pytania, która z tych
trzech liczb się psuje i dlaczego. Trzy wielkości są związane prawem Little'a
(niżej) — znając dwie, liczysz trzecią i sprawdzasz, czy pomiar „się spina”.

**Częsta pomyłka.** „Przepustowość = liczba wysłanych żądań na sekundę”. Raport
generatora ruchu, który pokazuje *ile wysłał*, nic nie mówi o tym, *ile system
zrobił*. W ćw. 4 aplikacja dostaje 6 żądań/s, a kończy 2.05/s — reszta czeka
w gnieździe i w pętli zdarzeń. Zawsze podawaj **osiągnięte** tempo (ukończone /
czas do ostatniej odpowiedzi), nie zadane.

---

## Czekanie vs obsługa

**Definicja.** Czas odpowiedzi rozkładasz na dwie części:
**R = czas czekania (W_q) + czas obsługi (S)**. Obsługa to praca, którą ktoś
faktycznie wykonuje dla żądania (tu: generacja u dostawcy, kilka milisekund
kodu aplikacji). Czekanie to czas, w którym żądanie stoi w kolejce do
**zasobu**: slotu semafora, połączenia w puli, wątku w puli, procesu
gunicorna, „mocy” dostawcy.

W aplikacji LLM pojawia się trzeci rodzaj czasu: **czekanie na odpowiedź z
zewnątrz**. Z punktu widzenia aplikacji generacja u dostawcy to „obsługa”, ale
procesor aplikacji w tym czasie nic nie robi — korutyna jest zawieszona na
`await`. Dlatego w tym kursie „czekanie” zawsze znaczy **czekanie na zasób
przed wywołaniem**, a „obsługa” — **samo wywołanie LLM** (span `llm.call`).
Aplikacja raportuje je osobno: atrybut `llm.queue.wait_ms` i histogram
`llm_queue_wait_seconds` (czekanie na semafor) oraz `llm_call_duration_seconds`
(wywołanie).

**Intuicja.** Urząd: numerek z automatu i czas przy okienku. Pani w okienku
obsługuje każdego w 3 minuty — to S. Jeśli spędziłeś w urzędzie godzinę, to 57
minut było czekaniem i *żadna* optymalizacja pracy w okienku (S z 3 do 2.5
minuty) nie jest tym, czego potrzebujesz. Potrzebujesz więcej okienek albo
mniej petentów naraz.

**Po co to.** To pierwsza decyzja diagnostyczna: czy żądanie jest wolne, bo
**obsługa** jest wolna (dostawca generuje długo, wolny pierwszy token), czy
dlatego, że **czeka** (za mała pula, limit dostawcy, kolejka za długimi
żądaniami)? Naprawy są zupełnie inne. W ćw. 6 przy 4 slotach i ruchu 20/s
czekanie ma p50 32 s, a wywołanie LLM p50 1.06 s — 97% czasu żądania to
kolejka.

**Częsta pomyłka.** Szukanie przyczyny w profilu CPU. Czekanie nie zużywa CPU
— zawieszona korutyna i wątek w `Condition.wait` są w profilu niewidoczne albo
wyglądają jak „bezczynność”. Czekanie widać w trace (luka między przybyciem a
`llm.call`, span `llm.queue_wait`) i w metrykach zasobów (zajętość = limit).

---

## System jako sieć kolejek

**Definicja.** **Kolejka** to miejsce, w którym żądania czekają na **serwer**
(w sensie teorii kolejek: cokolwiek, co obsługuje jedno żądanie naraz — slot,
wątek, połączenie, proces). Zbiór *c* identycznych serwerów z jedną kolejką to
**stacja obsługi**. Aplikacja LLM to **sieć** takich stacji ustawionych jedna
za drugą — żądanie przechodzi przez każdą i w każdej może czekać:

```
 klient (k6)
   │  backlog gniazda (jądro) ── proces gunicorna / uvicorna    [ćw. 7]
   ▼
 pętla zdarzeń asyncio (1 wątek)  ◄── blokada pętli: wszyscy czekają   [ćw. 4]
   │
   ├─► pula wątków anyio (40)     ◄── kod synchroniczny w `def`        [ćw. 5]
   │
   ├─► limit kolejki / odrzucanie (503 + Retry-After)                  [ćw. 12]
   ▼
 semafor LLM (sloty per klasa: krótkie / długie)                       [ćw. 1, 6, 12]
   │
   ├─► limiter tempa (RPM / ITPM / OTPM wg nagłówków dostawcy)         [ćw. 8]
   ▼
 pula połączeń httpx2 (max_connections)                               [ćw. 6]
   │                                     ┌─► kolejka zadań Redis + worker [ćw. 14]
   ▼                                     │
 dostawca LLM: kolejka u dostawcy → moc generacji (np. 8 naraz) → 429/529 [ćw. 8, 9, 11]
```

Każda stacja ma swój **limit** (rozmiar), swoją **kolejkę** (jawną albo
ukrytą) i swój sposób **zawodzenia** po przepełnieniu: kolejka rośnie w
nieskończoność, żądanie dostaje wyjątek (`PoolTimeout`), błąd HTTP (429, 529,
503) albo połączenie zostaje zerwane (backlog gniazda pełny).

**Intuicja.** Lotnisko: kolejka do odprawy, kontrola bezpieczeństwa, bramka,
pas startowy. Pasażer może czekać w każdym punkcie; to, że odprawa jest szybka,
nic nie da, jeśli kontrola ma jedno stanowisko. **Wąskie gardło** to stacja,
której wykorzystanie pierwsze dochodzi do 100% — za nią ruch jest „rozrzedzony”,
przed nią rośnie kolejka.

**Po co to.** Mapa stacji to lista miejsc, gdzie szukać czekania, i lista
liczników, które musisz mieć: dla każdej stacji **zajętość** (ile slotów
zajętych), **czekający** (ile w kolejce) i **wiek najstarszego czekającego**.
Aplikacja kursu wystawia je dla semafora (`llm_inflight`, `llm_waiting`,
`llm_oldest_waiting_age_seconds`), atrapa — dla dostawcy
(`mock_llm_generating`, `mock_llm_provider_queue`,
`mock_llm_oldest_inflight_seconds`), eksporter kolejki zadań — dla Redisa
(`kolejka_lag`, `kolejka_wiek_najstarszego_s`).

**Częsta pomyłka.** „Kolejki mamy tylko tam, gdzie jest napisane `Queue`”.
Każdy limit tworzy kolejkę, także niejawną: `asyncio.Semaphore` trzyma listę
czekających korutyn, pula httpx2 — listę czekających na połączenie, anyio —
na token wątku, jądro — na `accept()`. Najgroźniejsze są te, których nie
mierzysz: w ćw. 6 pula połączeń (8) mniejsza niż semafor (64) tworzy kolejkę,
której span `llm.queue_wait` w ogóle nie pokazuje — czas czekania na
połączenie wlicza się do „wywołania LLM”. Dowodem jest dopiero licznik po
stronie dostawcy: `mock_llm_generating` nigdy nie przekracza 8.

---

## Prawo Little'a

**Definicja.** Dla dowolnego stabilnego systemu (takiego, który na dłuższą
metę kończy tyle, ile dostaje) średnio:

> **L = λ · W**

gdzie **L** — średnia liczba żądań w systemie, **λ** — średnia intensywność
dopływu (= przepustowość, gdy system nadąża), **W** — średni czas pobytu w
systemie. Prawo nie zależy od rozkładów, kolejności obsługi ani liczby
serwerów. Działa dla całego systemu i dla każdej stacji osobno (np. dla samego
semafora: L = liczba zajętych slotów, W = czas wywołania LLM).

**Intuicja.** Bar: przychodzi 30 osób na godzinę, każda siedzi średnio 2
godziny → w środku jest średnio 60 osób. Nie trzeba nikogo liczyć przy drzwiach.

**Po co to.** Trzy zastosowania, wszystkie w kursie:

1. **Pojemność z rozmiaru puli.** Stacja z *c* slotami i czasem obsługi *S*
   nie przepuści więcej niż **X_max = c / S**. Po ćw. 6 semafor krótkich ma 32
   sloty, a streszczenie trwa 1.06 s: X_max = 32 / 1.06 ≈ **30.2/s**. Rampa w
   ćw. 3 mierzy dokładnie to: tempo rośnie 8 → 15 → 20.5 → 29.2 → 29.8 →
   30.2/s i staje, `llm_inflight` dochodzi do 32 i się przykleja. Przy 4
   slotach (szkielet) X_max = 4 / 1.05 ≈ **3.8/s** — dlatego w ćw. 2 ruch
   4/s wystarcza, żeby kolejka rosła.
2. **Rozmiar puli z ruchu.** Ile slotów potrzeba dla 20 streszczeń/s?
   L = 20 × 1.06 = **21.2** zajętych średnio. Mniej niż 21 slotów = kolejka
   rośnie bez końca; dokładnie 22 = system na granicy, z ogromnym czekaniem
   (patrz „kolano” niżej). Margines liczysz w czytance 01a.
3. **Kontrola spójności pomiaru.** W ćw. 7 gunicorn dostaje 15 żądań/s po
   3.5 s → L = 15 × 3.5 ≈ **52** żądań naraz. Workery synchroniczne obsługują
   jedno żądanie na proces; 29 procesów to X_max = 29 / 3.5 ≈ 8.3/s (zmierzone
   9.05/s — część wywołań była krótsza). Dwa procesy UvicornWorker po 32 sloty
   to 64 / 3.5 ≈ 18.3/s > 15/s — mieści się.

**Little przy W liczonym w minutach.** Prawo nie zna jednostek, ale skutki
skali są brutalne. Analiza trwa średnio ~153 s (generacja U[60, 240] s +
kilka sekund TTFT). Przy dopływie zaledwie **0.4 analizy/s**:
L = 0.4 × 153 ≈ **61** analiz trwa naraz. Pula 16 slotów dla długich daje
X_max = 16 / 153 ≈ **0.105/s** — czterokrotnie za mało. W ćw. 12 po 180 s
dopływu: przyszło 73 długich, zaległość 16 w toku + 46 czeka (rachunek:
(0.4 − 0.105) × 180 ≈ 53 nadmiaru). Ten sam rachunek przy W = 120 s ciszy
dostawcy (ćw. 10): 2 żądania/s × 120 s = 240 potrzebnych slotów — 32 sloty
zapełniają się w 16 s, potem wszyscy czekają.

**Częsta pomyłka.** Stosowanie Little'a do systemu niestabilnego. Gdy
λ > X_max, „średnie L” nie istnieje — kolejka rośnie liniowo z czasem testu, a
każda „średnia latencja” z raportu zależy od tego, jak długo trwał test.
Druga pomyłka: mieszanie λ wejścia z X wyjścia. W systemie przeciążonym użyj
X (osiągniętego) i W ukończonych żądań — inaczej rachunek się nie zamknie.

---

## Wykorzystanie i czas oczekiwania: kolano krzywej

**Definicja.** **Wykorzystanie** (*ρ*, *utilization*) stacji to odsetek czasu,
w którym jej serwery pracują: **ρ = λ · S / c**. Kluczowe zjawisko teorii
kolejek: czas czekania nie rośnie z ρ liniowo, tylko jak **1 / (1 − ρ)** —
powoli przy małym obciążeniu i gwałtownie, gdy ρ zbliża się do 1. Punkt, w
którym krzywa „zakręca w górę”, to **kolano**.

Najprostszy model, **M/M/1** (dopływ Poissona — przybycia niezależne,
wykładniczy czas obsługi, jeden serwer, kolejka bez limitu), ma wzory
zamknięte (μ = 1/S — tempo obsługi):

> **W = 1 / (μ − λ) = S / (1 − ρ)**  **W_q = ρ · S / (1 − ρ)**  **L_q = ρ² / (1 − ρ)**

Interpretacja: przy ρ = 0.5 żądanie spędza w systemie **2×** czas obsługi,
przy 0.9 — **10×**, przy 0.99 — **100×**. Dla S = 1.06 s (streszczenie):

| ρ | W (całość) | W_q (czekanie) | W / S | L_q (średnio w kolejce) |
|---|---|---|---|---|
| 0.50 | 2.12 s | 1.06 s | 2 | 0.5 |
| 0.70 | 3.53 s | 2.47 s | 3.3 | 1.6 |
| 0.80 | 5.30 s | 4.24 s | 5 | 3.2 |
| 0.90 | 10.6 s | 9.54 s | 10 | 8.1 |
| 0.95 | 21.2 s | 20.1 s | 20 | 18 |
| 0.99 | 106 s | 105 s | 100 | 98 |

**M/M/c** (ten sam dopływ, *c* serwerów, wspólna kolejka) zachowuje się
jakościowo tak samo, ale kolano przesuwa się **w prawo i robi się ostrzejsze**,
im więcej serwerów. Wiele serwerów „wygładza” przypadkowe skupiska przybyć:
gdy jeden jest zajęty, inny akurat się zwalnia. Rachunek (wzór Erlanga C,
skrypt weryfikacyjny kursu) dla c = 32 i S = 1.06 s:

| ρ | λ | P(trzeba czekać) | W_q |
|---|---|---|---|
| 0.70 | 21.1/s | 4% | 0.004 s |
| 0.80 | 24.2/s | 16% | 0.03 s |
| 0.90 | 27.2/s | 46% | 0.15 s |
| 0.95 | 28.7/s | 70% | 0.46 s |
| 0.99 | 29.9/s | 93% | 3.1 s |

Porównaj z M/M/1 przy ρ = 0.9: tam czekanie to 9× czas obsługi, tu 0.14×.
Ale przy 0.99 czekanie i tak eksploduje. Rampa z ćw. 3 pokazuje to na żywo:
do ~20/s czekanie p90 = 0, przy 29.2/s (ρ ≈ 0.97) — 1.6 s, przy 30.2/s —
9.7 s i rośnie z każdą sekundą testu.

**Zmienność** to drugi, równie ważny czynnik. Czas czekania rośnie z
wariancją przybyć i czasów obsługi. Ruch „wszystkie streszczenia po ~1 s” to
mała wariancja; ruch mieszany „80% po 1 s + 20% po 60–240 s” to wariancja
gigantyczna — przy tym samym średnim ρ kolejka jest wielokrotnie dłuższa, a
krótkie żądania czekają za długimi (head-of-line blocking, czytanka 01a, ćw. 12).

**Intuicja.** Kasa w sklepie przy 50% zajętości: zwykle podchodzisz od razu,
czasem czekasz na jedną osobę. Przy 95% zawsze ktoś stoi, a jedna osoba z
pełnym wózkiem (duża wariancja) zatrzymuje całą kolejkę na kwadrans. Dziesięć
kas z jedną kolejką (M/M/c) radzi sobie dużo lepiej niż dziesięć kas z osobnymi
kolejkami — ale pod warunkiem, że wózek z kwadransem zakupów nie trafia do
wspólnej kolejki z koszykami.

**Po co to.** Wyjaśnia, dlaczego „system pracuje na 85% i jest w porządku”
potrafi jednego dnia zamienić się w „p99 = minuta” po wzroście ruchu o 10%.
Wyjaśnia też, dlaczego planujesz pojemność **z marginesem** (docelowe ρ 0.7–0.8,
nie 0.95) i dlaczego separujesz klasy żądań o różnych czasach.

**Częsta pomyłka.** Traktowanie wzorów M/M/1 jako prognozy liczbowej dla
prawdziwego systemu. Rzeczywiste czasy LLM nie są wykładnicze, przybycia z k6
nie są Poissona (`constant-arrival-rate` wysyła równo co 1/λ), sloty nie są
jedną stacją. Model daje **kształt** (gdzie kolano, co się dzieje przy ρ → 1,
że wariancja szkodzi) — liczby bierzesz z pomiaru (rampa, ćw. 3).

---

## Gdy dopływ przekracza pojemność

**Definicja.** Przy λ > X_max system jest **przeciążony**: kolejka rośnie
liniowo w tempie **λ − X_max**, a czas czekania k-tego żądania (przy równym
dopływie) wynosi w przybliżeniu **k / X_max − k / λ**. Nie istnieje żaden stan
ustalony. Po zakończeniu dopływu system jeszcze długo pracuje — **opróżnianie**
(*drain*) trwa około **zaległość / X_max**.

**Intuicja.** Wanna z odpływem 3.8 l/s i kranem 20 l/s. Poziom wody rośnie o
16 l/s i nie ma znaczenia, czy odpływ jest „szybki” — liczy się różnica.

**Po co to.** Ćw. 6, rachunek do sprawdzenia na pomiarze: 4 sloty, S = 1.06 s →
X_max = 3.77/s; dopływ 20/s × 15 s = 300 żądań. Kolejka rośnie o 16.2/s.
150. żądanie czeka 150 / 3.77 − 150 / 20 ≈ **32.3 s** (zmierzone p50: 32.3 s),
297. — 297 / 3.77 − 297 / 20 ≈ **63.9 s** (zmierzone p99: 63.1 s). Opróżnienie
300 żądań trwa 300 / 3.77 ≈ 80 s, choć dopływ trwał 15 s. Przy wywołaniach
wielominutowych drain liczy się w minutach: w ćw. 12 po końcu dopływu zostaje
16 długich w toku i 8 czekających; 24 / 0.105 ≈ 230 s jako górne oszacowanie
(część pracy jest już zrobiona) — zmierzone 213 s.

**Częsta pomyłka.** Kończenie testu razem z dopływem. Raport k6 z ostatniej
sekundy dopływu nie zawiera żądań, które jeszcze czekają — a to one są
najgorsze. Testy w kursie mierzą **zaległość na koniec dopływu** i **czas
opróżniania** osobno (`scripts/pomiar.py`), a k6 ma `gracefulStop` dłuższy niż
najdłuższe żądanie (domyślne 30 s zerwałoby wielominutowe żądania w toku i
zafałszowało wynik — zmierzone przy budowie kursu).

---

## Percentyle i ogon

**Definicja.** **Percentyl p** (p50, p90, p99) to wartość, poniżej której
leży p% pomiarów. p50 = mediana — „typowe” żądanie; p99 — 1 na 100 jest
gorsze. **Ogon** to górna część rozkładu (p99, p99.9, max). Percentyli nie
wolno uśredniać (średnia p99 z pięciu instancji ≠ p99 całości) — liczy się je
z połączonego rozkładu, np. z histogramu: `histogram_quantile(0.99, sum by (le)(rate(..._bucket[1m])))`.

**Intuicja.** Średnia płaca w firmie z prezesem jest bez sensu; mediana mówi,
ile zarabia typowy pracownik, p99 — ile zarabia zarząd. Latencja ma ten sam
problem: kilka żądań po 2 minuty zrobi ze „średniej 1.5 s” liczbę, która nie
opisuje nikogo.

**Po co to.** Ogon jest tym, co czują użytkownicy i co mnoży się w systemie.
Strona, która woła 10 usług, trafi przynajmniej raz w p99 z prawdopodobieństwem
1 − 0.99¹⁰ ≈ **9.6%**, przy 50 wywołaniach — **39.5%**. Ogon jest też pierwszym
miejscem, gdzie widać kolejkę: w rampie z ćw. 3 p90 czekania rośnie od zera
wcześniej niż mediana. I wreszcie — w aplikacji LLM ogon jest **zaprojektowany**:
analizy trwające 60–300 s to nie anomalia, tylko osobna klasa. Dlatego kurs
raportuje percentyle **per klasa** (krótkie / długie), nie łącznie.

**Częsta pomyłka.** p99 z małej próby. Z 300 żądań nad p99 leżą 3 — jedna
zmiana sekwencji przesuwa p99 o sekundy. Druga: histogram z kubełkami
kończącymi się na 10 s dla czasów liczonych w minutach — wszystko powyżej
ląduje w `+Inf` i kwantyl jest „ucięty”. Histogramy kursu (np. czekanie u
dostawcy w atrapie) mają kubełki do 300 s właśnie dlatego.

---

## Model otwarty vs zamknięty i coordinated omission

**Definicja.** Generator ruchu działa w jednym z dwóch modeli:
- **Zamknięty** — stała liczba *N* „użytkowników” (w k6: VU, executor
  `constant-vus`); każdy wysyła żądanie, **czeka na odpowiedź**, odczekuje
  *Z* (czas namysłu) i wysyła kolejne. Przepustowość wynika z odpowiedzi:
  **X = N / (R + Z)** (prawo czasu odpowiedzi — Little dla zamkniętej pętli).
- **Otwarty** — żądania przychodzą w zadanym tempie λ, **niezależnie** od
  tego, czy poprzednie się skończyły (k6: `constant-arrival-rate`,
  `ramping-arrival-rate`). Tak zachowuje się większość prawdziwego ruchu:
  klienci nie wiedzą o sobie nawzajem.

**Coordinated omission** to błąd pomiaru modelu zamkniętego: gdy system
zwalnia, generator sam **wstrzymuje** wysyłanie (VU czeka na odpowiedź), więc
nie zmierzy żądań, które w otwartym świecie przyszłyby w tym czasie i
czekałyby w kolejce. Generator „koordynuje się” z systemem i pomija dokładnie
te pomiary, które byłyby najgorsze.

**Intuicja.** Badanie kolejki w urzędzie przez 4 ankieterów, z których każdy
wchodzi dopiero, gdy poprzedni wyjdzie. Nigdy nie zobaczą kolejki, bo sami
jej nie tworzą — a prawdziwi petenci przychodzą o 8:00 wszyscy naraz.

**Po co to.** Ćw. 2, ta sama nominalna intensywność ~4 żądania/s przy
pojemności ~3.8/s (4 sloty):
- zamknięty, 4 VU bez pauzy: 3.75/s (rachunek: 4 / 1.07 s ≈ 3.74), p99 **1.57 s**,
  czekanie 0 — „wszystko OK”;
- otwarty, 4/s: osiągnięte 3.52/s, p99 **4.41 s**, czekanie na semaforze p99
  3.28 s — kolejka rośnie, bo ρ ≈ 1.05.

Z pauzą 1 s te same 4 VU dają 4 / (1.08 + 1) ≈ **1.92/s** (zmierzone 1.92/s) —
„4 VU” to nie jest „4 żądania/s”. W modelu otwartym k6 ma licznik
`dropped_iterations`: gdy zabraknie VU do wysłania żądania o czasie, pomiar
jest nieważny (generator sam stał się wąskim gardłem) — zawsze go sprawdzaj.

**Częsta pomyłka.** „Dałem 100 VU, więc to test na 100 użytkowników i jest
realistyczny”. 100 VU bez pauzy przy R = 1 s to ~100 żądań/s, przy R = 10 s —
10/s: obciążenie maleje dokładnie wtedy, gdy system ma problem. Testy
pojemności, SLO i kolejek w kursie są **otwarte**; zamknięty służy tylko jako
kontrprzykład (i do modelowania puli workerów, która naprawdę jest zamknięta —
np. worker kolejki zadań z `--max-async-tasks`).

---

## RED i USE dla tej aplikacji

**Definicja.** Dwie listy kontrolne metryk:
- **RED** (dla usług, „z zewnątrz”): **R**ate — tempo żądań, **E**rrors —
  odsetek błędów, **D**uration — rozkład czasu (percentyle).
- **USE** (dla zasobów, „od środka”): **U**tilization — zajętość,
  **S**aturation — nasycenie (ile czeka na zasób), **E**rrors — błędy zasobu.

W tej aplikacji:

| Warstwa | RED / USE | Metryka w kursie |
|---|---|---|
| endpointy | R, E, D | `app_requests_total{endpoint,klasa,wynik}`, `app_request_duration_seconds_bucket` |
| semafor LLM | U, S | `llm_inflight{klasa}` vs liczba slotów; `llm_waiting`, `llm_oldest_waiting_age_seconds`, `llm_queue_wait_seconds` |
| wywołanie LLM | D, E | `llm_call_duration_seconds{dostawca,wynik}`, `llm_ttft_seconds` |
| HTTP do dostawcy | R, E | `llm_http_attempts_total`, `llm_http_responses_total{status}` (429, 529) |
| pętla zdarzeń | S | `app_event_loop_lag_seconds`, `/diag/ping` |
| dostawca (atrapa) | U, S, E | `mock_llm_generating`, `mock_llm_provider_queue`, `mock_llm_requests_total{status}`, `mock_llm_cancelled_total` |
| kolejka zadań | S | `kolejka_lag`, `kolejka_pending`, `kolejka_wiek_najstarszego_s` |
| klient (k6) | R, D | `k6_http_reqs_total`, `k6_http_req_duration_p99`, `k6_dropped_iterations_total` |

Ważne: `wynik` rozróżnia **ok, odrzucone, przeterminowane, anulowane,
timeout_dostawcy, limit_dostawcy, blad_dostawcy**. „Błąd” to w systemie z
backpressure kilka różnych rzeczy: szybkie 503 od nas jest **zdrowe**
(odmowa), 504 po minucie — nie.

**Intuicja.** RED to termometr pacjenta (gorączka, ma czy nie ma), USE —
badania narządów (który organ jest przeciążony). Najpierw RED mówi, *że*
jest źle i *gdzie* (który endpoint, która klasa); potem USE wskazuje, *który
zasób* jest nasycony.

**Po co to.** Pozwala zacząć każdą diagnozę od taniego przeglądu, a nie od
przypadkowego grzebania: „p99 krótkich wzrosło” (RED) → „`llm_inflight`
krótkich przyklejone do limitu, `llm_waiting` > 0” (USE semafora) → „u
dostawcy `generating` daleko od jego mocy” → wąskie gardło jest u nas
(ćw. 6, finał).

**Częsta pomyłka.** Patrzenie tylko na **U** bez **S**. Zasób zajęty w 100%
bez kolejki to zasób idealnie dociążony; problemem jest nasycenie — ile
czeka i jak długo. I odwrotnie: semafor może mieć zajętość 4 z 4 przy
„niedociążonym” dostawcy — to znaczy, że limitem jest semafor, nie dostawca.

---

## Specyfika LLM: TTFT, tokeny, minuty, limity, koszt

**Definicja.** Wywołanie LLM różni się od typowego wywołania bazy danych:
- **TTFT** (*time to first token*) — czas od wysłania żądania do pierwszego
  fragmentu odpowiedzi; obejmuje kolejkę u dostawcy i przetworzenie wejścia.
  Na prawdziwym Claude (Haiku 5.5, sprawdzone przy budowie kursu) mediana
  0.48–0.72 s, ogon do ~1.2 s.
- **Tempo generacji** (tokeny/s) — po pierwszym tokenie reszta płynie ze
  stałą prędkością: realnie ~225–300 tokenów/s. Czas całkowity ≈ TTFT +
  tokeny_wyjścia / tempo: odpowiedź 700 tokenów ≈ 0.48 + 700 / 225 ≈ 3.6 s
  (zmierzone 3.62 s). Atrapa domyślnie: TTFT log-normalny z medianą 450 ms,
  250 tokenów/s.
- **Czasy od sekund do minut.** Długie zadania (analiza całej teczki szkody,
  modele z rozumowaniem) trwają **60–300 s**: albo długo milczą przed pierwszym
  tokenem (długi TTFT), albo długo generują (długi strumień), albo robią pauzy.
  To pełnoprawna klasa ruchu, nie anomalia.
- **Limity dostawcy** — liczone per minuta: **RPM** (żądania), **ITPM**
  (tokeny wejścia), **OTPM** (tokeny wyjścia). Przekroczenie → **429** z
  `retry-after` i nagłówkami `anthropic-ratelimit-*-remaining/-reset`.
  Osobny przypadek to **529 overloaded** — dostawca nie ma wolnej mocy (w SDK
  `OverloadedError`, odrębna klasa od `RateLimitError`).
- **Koszt** — płacisz za tokeny wejścia i wyjścia (Haiku 5.5: $0.10 / $0.50 za
  milion). Ponowienie wysyła wejście jeszcze raz; porzucona generacja zużyła
  moc dostawcy i limit tokenów.

**Intuicja.** Dostawca LLM to drukarnia na zamówienie: najpierw czekasz, aż
przyjmą zlecenie i przygotują maszynę (TTFT), potem strony wychodzą w stałym
tempie (tokeny/s). Drukarnia ma limit zleceń i stron na minutę dla Twojej
firmy (RPM/OTPM) i własną moc maszyn wspólną dla wszystkich klientów (529).
Każde zlecenie powtórzone „na wszelki wypadek” kosztuje drugi raz.

**Po co to.** Limit tokenów to też pojemność i liczy się jak Little:
profil `limity` atrapy ma OTPM 12 000; streszczenie to 200 tokenów wyjścia →
12 000 / 200 = **60 streszczeń/min = 1/s**, niezależnie od liczby slotów.
Ruch 3/s × 60 s = 180 żądań na pojemność 60 — w ćw. 8 szkielet zbiera 133
odpowiedzi 429 u atrapy. Po naprawie 429 znika, ale **nadmiar czeka u nas**
(czekanie p99 58 s) — limiter po stronie klienta nie zwiększa pojemności,
przenosi kolejkę do miejsca, które kontrolujesz.

**Częsta pomyłka.** „U prawdziwego dostawcy limitów nie widać, więc ich nie
ma”. Na koncie użytym przy budowie kursu limity były tak wysokie (RPM 13 000,
OTPM 2 M), że 429 było praktycznie nieosiągalne — dlatego limity ćwiczysz na
atrapie. Na produkcji z niższym tierem albo przy dużych wsadach (ITPM) to
pierwsza ściana, w którą uderzysz.

---

## Wywołania wielominutowe

**Definicja.** Żądanie, którego czas obsługi liczy się w minutach (w kursie:
60–300 s), zmienia wszystkie poprzednie rachunki o rząd albo dwa rzędy
wielkości: zajmuje slot semafora, połączenie i slot u dostawcy **na minuty**,
a każdy błąd timeoutu czy ponowienia kosztuje **minuty**.

**Intuicja.** Myjnia samochodowa, do której raz na jakiś czas wjeżdża
autobus. Myjnia jest „szybka”, dopóki autobusy nie zajmą wszystkich stanowisk
— wtedy auta osobowe stoją pół godziny.

**Po co to.** Kurs traktuje je jako główny przypadek, nie przypis:
- **Zajętość slotów minutami.** L = λ · W: przy W = 153 s nawet 0.4/s daje 61
  równoległych analiz (wyżej). Każde wywołanie trzyma slot ~150 razy dłużej
  niż streszczenie.
- **Head-of-line blocking.** We wspólnej puli 32 slotów (ćw. 12, krótkie 4/s +
  długie 0.4/s) krótkie czekają **p50 29 s, p99 131 s** przy obsłudze ~1 s —
  bo sloty zjadły analizy. Osobne pule (32 / 16): czekanie krótkich p99 = 0.
- **Timeouty.** Domyślny read timeout SDK to 600 s; timeout k6 — 60 s;
  gunicorn z workerami sync zabija worker po 30 s. Każdy z nich inaczej
  „przecina” wielominutowe żądanie (czytanka 08a, ćw. 10).
- **Ponowienia mnożą minuty.** 4 analizy z 90 s ciszy przy timeoucie 60 s i
  domyślnych 2 ponowieniach SDK: 3 × 60 s ≈ 180 s czekania i błąd 504 po
  181.6–191.6 s, 10 porzuconych generacji u dostawcy (ćw. 10).
- **Anulowanie.** Klient, który się rozłączył po 20 s, nie zwalnia slotu sam
  z siebie: bez anulowania dostawca generuje „do nikogo” jeszcze 173 s;
  z anulowaniem slot wraca w 0.7 s (ćw. 10).
- **Drain.** Po końcu dopływu długie żądania pracują jeszcze minuty — wiek
  najstarszego (`mock_llm_oldest_inflight_seconds`) i zaległość mierzysz po
  zakończeniu ruchu, nie tylko w trakcie.

**Częsta pomyłka.** Testowanie na profilu sekundowym i ekstrapolacja. Profil
„wszystko po sekundzie” nie odkryje timeoutu 60 s w k6, 30 s w gunicornie,
pingu utrzymującego połączenie ani tego, że `timeout` SDK nie jest limitem
całkowitym. Profil sekundowy w kursie służy tylko do szybkiego smoke; ćwiczenia
o timeoutach, backpressure i finał trwają wall-clock po kilka minut.

---

## Jak czytać trace, metryki i profil w tym kursie

**Definicja.** Trzy rodzaje telemetrii (wszystkie przez OTel do Grafany:
Tempo, Prometheus, Pyroscope):
- **Trace** — drzewo **spanów** jednego żądania: każdy span ma początek,
  koniec, atrybuty i rodzica. Pokazuje, **gdzie żądanie spędziło czas**,
  łącznie z czasem, w którym nikt nic nie liczył. Struktura w aplikacji:
  ```
  POST /claims/{n}/summary            (korzeń: app.klasa, app.wynik, llm.queue.wait_ms)
   ├─ llm.queue_wait                  (czekanie na semafor — rodzeństwo, nie rodzic llm.call)
   └─ llm.call                        (llm.dostawca, llm.cb.stan)
       └─ anthropic.messages.create   (natywny span SDK)
           └─ POST                    (httpx2: pojedyncza próba HTTP)
  ```
  Luki między spanami to czas, którego nikt nie zarejestrował: blokada pętli,
  czekanie w puli połączeń, backoff między próbami. Kilka spanów `POST` pod
  jednym `anthropic.messages.create` = ponowienia SDK.
- **Metryki** — agregaty w czasie (liczniki, histogramy, gauge). Pokazują
  **ile i jak często** w całym ruchu: tempo, percentyle, zajętość, kolejki.
  Nie powiedzą, *które* żądanie, ale powiedzą, *że* problem dotyczy 30% ruchu.
- **Profil** (Pyroscope) — próbkuje stosy wywołań i pokazuje, **w których
  funkcjach są wątki** (CPU albo wall). Odpowiada na pytanie „co robi kod”.

**Intuicja.** Trace to nagranie z kamery jednego klienta w sklepie; metryki
to licznik przy drzwiach i kamera z lotu ptaka; profil to zdjęcie, co w danej
chwili robią pracownicy. Klient stojący w kolejce jest na nagraniu (trace),
w statystyce (metryka czekających), ale na zdjęciu pracowników go nie ma.

**Po co to.** Każdy rodzaj odpowiada na inne pytanie i ma ślepe plamki:
- Profil **nie widzi zawieszonej korutyny**. Żądanie czekające 60 s na
  `await` (semafor, LLM, sleep backoffu) nie zajmuje wątku — nie ma go na
  żadnym stosie, w żadnym trybie profilu. Sprawdzone przy budowie kursu:
  `await` na LLM jest niewidoczne zarówno w profilu CPU, jak i wall.
- Profil **widzi blokadę**: synchroniczny klient LLM w handlerze async w
  profilu CPU jest prawie niewidoczny (0.4% — czeka na gnieździe, nie liczy),
  w profilu wall już tak (13%, `SyncStream.read`). Dlatego w ćw. 4 profil jest
  tylko potwierdzeniem; główny objaw jest systemowy (przepustowość, /health).
- Trace **nie pokaże kolejki, w której nikt nie postawił spanu** — czekanie w
  puli połączeń httpx2 nie ma osobnego spanu (ćw. 6), backlog gniazda w ogóle
  nie jest w trace. Tam pomagają metryki zasobów.
- Metryki **uśredniają**: histogram czekania z ruchu mieszanego bez etykiety
  `klasa` ukryje, że krótkie czekają minutę.

**Częsta pomyłka.** „Profil ma 2% CPU w handlerze, więc handler nie jest
problemem”. W aplikacji I/O-bound prawie wszystko, co ważne, dzieje się
**między** próbkami profilu CPU. Druga: span `llm.queue_wait` jako **rodzic**
`llm.call` — wtedy czas wywołania wlicza się w czekanie i odczyt jest fałszywy;
w kursie czekanie jest rodzeństwem wywołania (ćw. 1).

---

## Metodyka diagnozy w tym kursie

**Definicja.** Każde ćwiczenie i incydent idzie tą samą pętlą:
1. **Objaw z zewnątrz** (RED, raport k6 — z osiągniętym tempem i
   `dropped_iterations`).
2. **Hipoteza przed obserwacją** — zanim otworzysz Grafanę, zapisz, co
   spodziewasz się zobaczyć i dlaczego (Little, kolano, ρ).
3. **Rozkład czasu** — trace: czekanie vs obsługa vs TTFT vs luki.
4. **Zasób** — USE: który limit jest przyklejony do maksimum i gdzie rośnie
   kolejka (u nas czy u dostawcy).
5. **Rachunek** — czy liczby spinają się z L = λW. Jeśli nie, szukasz kolejki,
   której nie mierzysz.
6. **Naprawa i pomiar ponowny** — ten sam ruch, ta sama długość testu, buggy
   vs fixed; plus stan po końcu dopływu.

**Intuicja.** Lekarz: wywiad, hipoteza, badanie, wynik, kontrola po leczeniu.
Hipoteza przed badaniem chroni przed „widzę wykres, więc wiem”.

**Po co to.** Systemy kolejkowe są nieintuicyjne: naprawa w jednym miejscu
przenosi kolejkę gdzie indziej (ćw. 8: 429 znika, czekanie u nas rośnie;
ćw. 6: więcej slotów przy zbyt małej puli połączeń nic nie daje). Rachunek
Little'a i pomiar po naprawie łapią takie przesunięcia.

**Częsta pomyłka.** Porównywanie przebiegów o różnej długości albo innym
modelu ruchu. W systemie przeciążonym p99 rośnie z długością testu — dwa
przebiegi są porównywalne tylko przy tym samym dopływie, czasie i modelu.

---

## Jak to się łączy (mapa)

```
            λ (dopływ, model OTWARTY)                         ćw. 2: zamknięty ukrywa kolejkę
                 │
                 ▼
  ┌──────── stacja: c slotów, czas obsługi S ────────┐        ρ = λ·S/c
  │ kolejka (W_q)  →  obsługa (S)                    │        L = λ·W        (ćw. 3)
  │                                                  │        W ~ S/(1−ρ)    (kolano)
  └──────────────────────────────────────────────────┘
     ▲ gdzie stacje:                                     gdy λ > c/S:
     │ pętla zdarzeń (ćw. 4) · pula wątków 40 (ćw. 5)        kolejka rośnie o λ − c/S
     │ semafor/pula połączeń (ćw. 6) · procesy (ćw. 7)       → limit + odrzucanie (ćw. 12)
     │ limity RPM/ITPM/OTPM, 429/529 (ćw. 8)                 → nie mnożyć ruchu retry (ćw. 9)
     │ kolejka zadań (ćw. 14) · cache/batching (ćw. 15–16)   → deadline, anulowanie (ćw. 10)
     │
  ruch mieszany: S od 1 s do 300 s → wariancja → head-of-line (ćw. 12) → osobne pule / kolejka zadań
  mierzysz: trace (czekanie vs obsługa) · metryki RED/USE · profil tylko dla CPU/blokady
```

Teraz przeczytaj `01a-teoria-kolejek-w-praktyce.md`, a potem zacznij od ćw. 1.
