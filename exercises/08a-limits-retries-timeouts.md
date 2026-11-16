# 08a. Czytanka: limity dostawcy, ponowienia, timeouty, fallback

Czytanka, nie ćwiczenie — bez zadań i kryteriów „done”. Cel: zrozumieć
mechanizmy, którymi aplikacja broni się przed dostawcą LLM i chroni dostawcę
przed sobą — zanim w bloku III zobaczysz lawinę 429, burzę ponowień, wiszące
minutami żądania i fallback, który pogarsza sprawę. Wszystkie te mechanizmy
mają wspólny mianownik: **zmieniają ruch, który dociera do dostawcy**, i
**czas, przez który żądanie trzyma zasoby**. Każde pojęcie w schemacie:

> **Definicja** → **Intuicja/analogia** → **Po co to** → **Częsta pomyłka**

Wracaj tu, gdy coś przestanie się spinać. Krótkie definicje są w `slownik.md`.

---

## Limity dostawcy: RPM, ITPM, OTPM

**Definicja.** Dostawca LLM ogranicza ruch **per organizacja / klucz** w
kilku wymiarach naraz, liczonych w oknie minutowym:
- **RPM** — żądania na minutę,
- **ITPM** — tokeny wejścia na minutę,
- **OTPM** — tokeny wyjścia na minutę.

Limity działają jak **kubełek z żetonami** (*token bucket*): kubełek ma
pojemność = limit i stale się dopełnia; każde żądanie zabiera żetony; gdy ich
brak — odpowiedź **429** (`anthropic.RateLimitError`) z nagłówkiem
`retry-after` (po ilu sekundach wrócić). Każda odpowiedź niesie stan kubełków:
`anthropic-ratelimit-{requests,input-tokens,output-tokens,tokens}-{limit,remaining,reset}`.
Osobny przypadek: **529 overloaded** (`anthropic.OverloadedError` — w SDK 2.x to
**nie** jest podklasa `InternalServerError`) — Twój limit jest w porządku, ale
dostawca nie ma wolnej mocy.

**Intuicja.** Karnet na siłownię z limitem wejść i limitem minut na bieżni na
godzinę (429: „wykorzystałeś swój limit, wróć za 2 minuty”) — a osobno sytuacja,
gdy wszystkie bieżnie są zajęte przez innych (529: „nie ma miejsca dla nikogo”).

**Po co to.** Limit to **pojemność** w sensie teorii kolejek: profil `limity`
atrapy ma RPM 120, ITPM 60 000, OTPM 12 000. Streszczenie generuje 200 tokenów,
więc OTPM przepuści 12 000 / 200 = **60 streszczeń/min = 1/s**, choć RPM
pozwoliłby na 2/s — wiąże najciaśniejszy wymiar. Ćw. 8: ruch 3/s × 60 s
(180 żądań na pojemność ~60) → u atrapy **133 × 429**, część żądań kończy się
błędem. Po dodaniu limitera po stronie klienta: **0 × 429**, wszystkie 180 OK,
ale nadmiar **czeka u nas** (czekanie p99 58 s). Limiter nie tworzy pojemności,
tylko przenosi kolejkę z dostawcy (gdzie objawia się błędami i ponowieniami)
do aplikacji (gdzie ją mierzysz i możesz ograniczyć — ćw. 12).

**Częsta pomyłka.** Limiter liczony tylko w żądaniach. Wymiar tokenowy
zmienia się z długością promptu i odpowiedzi — wsad 100 zgłoszeń po ~80
tokenów to 8 000 tokenów wejścia w jednym żądaniu; przy ITPM 60 000 mieści się
7.5 takich wsadów na minutę (czytanka 14a). Druga pomyłka: limiter, który
czeka na „sondę” — nagłówki limitów z pierwszej odpowiedzi. Odpowiedź bez
strumienia niesie nagłówki dopiero po całej generacji; przy wywołaniach
minutowych taka sonda wstrzymuje start procesu na minuty (zmierzone przy
budowie kursu: +10 s w teście z długą ciszą). Pierwszą falę ma trzymać pula
slotów, a nagłówki tylko korygują tempo.

---

## Ponowienia: kiedy i jak

**Definicja.** **Ponowienie** (*retry*) to wysłanie tego samego żądania po
błędzie przejściowym. Trzy decyzje:
1. **Co ponawiać** — błędy przejściowe: 429, 529, 5xx, zerwane połączenie. Nie
   ponawiać: 400 (błąd żądania — powtórka da to samo), 401/403. **Timeout**
   to przypadek szczególny: dostawca zwykle dalej pracuje nad poprzednią
   próbą, więc powtórka podwaja jego obciążenie i Twój czas (w kursie
   timeoutów nie ponawiamy).
2. **Kiedy** — **wykładniczy backoff**: przerwa rośnie z numerem próby
   (baza · 2ⁿ, z górnym limitem), z **jitterem** — losowym rozrzuceniem
   przerwy. **Pełny jitter**: przerwa ~ U(0, min(limit, baza · 2ⁿ)). Jeśli
   dostawca podał `retry-after`, ma pierwszeństwo.
3. **Ile** — limit prób per żądanie **i** globalny **budżet ponowień**
   (ponowienia jako ułamek wszystkich żądań w oknie czasu).

SDK `anthropic` 2.3 ma własną warstwę: domyślnie **`max_retries=2`** (3 próby),
przerwy 0.5–8 s, honoruje `retry-after`, ponawia także timeouty żądań bez
strumienia.

**Intuicja.** Dzwonisz do zajętej infolinii. Rozsądnie: odczekać, z każdą
próbą dłużej, i każdy dzwoniący trochę inaczej. Nierozsądnie: wszyscy
klienci po rozłączeniu dzwonią ponownie dokładnie po 1 sekundzie — centrala
dostaje fale coraz większe od pierwotnego ruchu.

**Po co to.** Dla baza = 0.5 s i limitu 8 s (rozwiązanie ćw. 9) przerwy kolejnych
prób losowane są z U(0, 0.5), U(0, 1), U(0, 2), U(0, 4) s… Klienci, którzy
dostali błąd w tej samej chwili, wracają rozproszeni w czasie, a nie jedną falą.

**Częsta pomyłka.** Backoff bez jittera („wykładniczy wystarczy”). Wszyscy,
którzy padli razem, wracają razem po 0.5 s, potem razem po 1 s — przeciążenie
przesuwa się w czasie, ale się nie rozmywa.

---

## Amplifikacja i burza ponowień

**Definicja.** **Amplifikacja ponowień** — stosunek prób HTTP wysłanych do
dostawcy do żądań, które przyszły do aplikacji. Warstwy się **mnożą**: 3 próby
aplikacji × 3 próby SDK = do **9** prób na jedno żądanie użytkownika (a każdy
proxy czy klient wyżej dokłada kolejny czynnik). **Burza ponowień** to
sytuacja, gdy przeciążony dostawca odpowiada błędami, ponowienia zwiększają
ruch, więc błędów jest więcej — system może zostać w przeciążeniu nawet po
ustąpieniu pierwotnej przyczyny (stan **metastabilny**).

**Intuicja.** Korek na wjeździe do miasta, w którym każdy kierowca, który nie
zmieścił się na rondo, objeżdża kwartał i próbuje jeszcze raz — ruch na rondzie
składa się głównie z tych samych aut, a nie z nowych.

**Po co to.** Ćw. 9, profil `przeciazenie` (moc 8 generacji + kolejka 8,
powyżej 529), ruch 10/s × 20 s:
- dwie warstwy ponowień bez jittera: **3.65 próby HTTP na żądanie** (730 prób,
  567 × 529), 163 sukcesy;
- jedna warstwa (SDK `max_retries=0`), pełny jitter, budżet 20%: **1.20 próby
  na żądanie** (88 × 529), 152 sukcesy.

Sukcesów jest prawie tyle samo — ponowienia bez kontroli **nie ratują żądań**,
tylko trzykrotnie obciążają dostawcę (i trzykrotnie kosztują wejście). Budżet
20% wyznacza sufit amplifikacji: 1 + 0.2 = 1.2 — dokładnie tyle zmierzono.

**Częsta pomyłka.** Ponowienia w kilku warstwach, „bo każda powinna być
odporna”. Wybierz **jedną** warstwę, która ponawia (z budżetem i jitterem), a w
pozostałych wyłącz ponowienia jawnie — dla SDK `max_retries=0`. Druga:
fallback ponawiający 529 u drugiego dostawcy — przeciążenie to nie awaria;
przeniesie burzę na zapasowego dostawcę.

---

## Timeouty: connect, read, write, pool — i czego nie mierzą

**Definicja.** Klient HTTP (httpx2, a przez niego SDK) ma cztery osobne
timeouty, wszystkie **per operacja**:
- **connect** — zestawienie połączenia TCP/TLS,
- **read** — czekanie na **kolejną porcję danych** z gniazda (czyli limit
  **bezczynności**, nie całości: każdy odebrany bajt resetuje zegar),
- **write** — wysłanie porcji danych,
- **pool** — czekanie na wolne połączenie w puli.

Domyślnie w SDK `anthropic` 2.3: connect 5 s, read / write / pool **600 s**.
**Żaden z nich nie jest limitem całkowitym.** Limit całkowity —
**deadline** — robisz w aplikacji: `asyncio.timeout(sekundy)` wokół całego
wywołania (z ponowieniami); po przekroczeniu zadanie jest anulowane.

Co oznacza „read” w praktyce, zależy od trybu:
- **bez strumienia** — odpowiedź przychodzi w całości po zakończeniu generacji,
  więc read musi pokryć **TTFT + całą generację**;
- **ze strumieniem** — read musi pokryć **najdłuższą przerwę między
  zdarzeniami** (w tym ciszę przed pierwszym tokenem).

**Intuicja.** Read timeout to „rozłącz się, jeśli rozmówca milczy dłużej niż
30 s”, a nie „rozłącz się po 30 s rozmowy”. Rozmowa może trwać godzinę, jeśli
rozmówca co chwilę coś mówi.

**Po co to.** Pomiary z budowy kursu (atrapa, SDK z `timeout=30`):
- strumień 150 s generacji z krótkim TTFT — **kończy się poprawnie po 148.9 s**:
  read 30 s nie przerwał 150-sekundowego wywołania;
- to samo z `asyncio.timeout(60)` — przerwane po **60.0 s**, atrapa notuje
  anulowaną generację (slot u dostawcy zwolniony);
- bez strumienia, 90 s ciszy — `APITimeoutError` dopiero po **91.3 s**: SDK
  ponowił dwa razy (3 × 30 s), u dostawcy zostały 3 porzucone generacje;
- strumień, pauza 40 s w środku — **`httpx2.ReadTimeout` po 30.5 s**.

W ćw. 10 szkielet ma domyślne 600 s: dostawca milczy 120 s, ruch 2/s × 30 s →
32 / 32 sloty zajęte, 28 czeka, ostatnia odpowiedź po **254 s**. Z read 15 s dla
krótkich: 504 po 15–25 s, ostatnia po 44.5 s, 59 generacji przerwanych.

**Częsta pomyłka.** `except anthropic.APITimeoutError` jako „obsługa
timeoutów”. Timeout **w trakcie strumienia** wychodzi jako **surowy
`httpx2.ReadTimeout`** — nie jest podklasą `APITimeoutError` i SDK go nie
ponawia. Odwrotnie: `except anthropic.APIConnectionError` łapie także
`APITimeoutError` (podklasa) i `PoolTimeout` — gałąź „zerwane połączenie”
nagle obsługuje timeouty.

---

## Cisza przed pierwszym tokenem i ping

**Definicja.** Przy długim TTFT (w kursie 60–180 s) przez minuty nie płyną
żadne dane. Dostawca może temu przeciwdziałać: wysłać **nagłówki odpowiedzi od
razu** i co jakiś czas zdarzenie SSE **`ping`** (w atrapie co 15 s). Każdy
ping resetuje read timeout klienta i timeouty bezczynności pośredników
(proxy, load balancer).

**Intuicja.** Rozmówca, który mówi „jeszcze sprawdzam…” co 15 sekund — nie
rozłączasz się, choć odpowiedzi wciąż nie ma.

**Po co to.** Strumień z 90 s ciszy przy read 30 s: bez pingu
`httpx2.ReadTimeout` po 30.0 s; z pingiem co 15 s — poprawnie po 90.1 s. W ćw.
10 (4 analizy: 90 s ciszy + 30 s generacji) szkielet bez strumienia z read
60 s i 2 ponowieniami SDK daje 504 po **181.6–191.6 s** (3 × 60 s) i **10
porzuconych generacji**; po przejściu na strumień (ping 15 s < read 60 s,
`max_retries=0`): 4 × 200 po **122.0 s**, 0 porzuconych. Read timeout ustawiasz
więc jako ≥ 2 × najdłuższa oczekiwana cisza **albo** ≥ 2 × odstęp pingu, gdy
dostawca pinguje.

**Częsta pomyłka.** „Aplikacja widzi pingi, więc może na nich mierzyć postęp”.
Iterator `MessageStream` SDK **nie zwraca** zdarzeń `ping` (zmierzone: licznik
pingów po stronie aplikacji = 0) — utrzymują połączenie na poziomie HTTP, ale
kod aplikacji ich nie dostaje.

---

## Budżet timeoutów warstw

**Definicja.** Na ścieżce żądania jest kilka zegarów: generator ruchu (k6),
proxy / menedżer procesów (gunicorn), deadline aplikacji, timeouty SDK. Spójny
**budżet timeoutów** to ich ułożenie od wewnątrz na zewnątrz:
**timeouty SDK (bezczynność) < deadline aplikacji (per klasa) < timeout
warstw zewnętrznych (proxy, k6)**. Wtedy to aplikacja decyduje, kiedy
przerwać — z czytelnym błędem (504 `przeterminowane`) i zwolnieniem zasobów.

**Intuicja.** Matrioszki: każda zewnętrzna musi być większa od wewnętrznej,
inaczej się nie domkną. Jeśli zewnętrzna (k6) jest mniejsza, „zamyka się” na
niedokończonej pracy, a wewnętrzna (aplikacja) dalej trzyma slot.

**Po co to.** Pułapki zmierzone przy budowie kursu:
- **k6** — domyślny timeout żądania **60 s**: 90-sekundowe wywołanie kończy
  się `status 0` / `request timeout` po 60.0 s i unieważnia test minutowy.
  Skrypty kursu ustawiają `timeout` jawnie (np. 400 s przy deadline długich
  330 s) i `gracefulStop` dłuższy niż najdłuższe żądanie;
- **gunicorn `-k sync`** — domyślny `--timeout 30` zabija worker przy 45-s i
  90-s wywołaniu (500 + `WORKER TIMEOUT`); z UvicornWorker żądanie 90 s
  kończy się 200;
- **deadline per klasa** w aplikacji (rozwiązanie ćw. 10): krótkie 30 s, długie
  330 s (ogon 300 s + zapas na kolejkę u dostawcy).

**Częsta pomyłka.** „Podnieśmy wszystkie timeouty do 10 minut”. Wtedy żaden
nie działa jako sygnał: zawieszony dostawca trzyma sloty przez 10 minut
(ćw. 10: ostatnia odpowiedź po 254 s przy 2 żądaniach/s), a test o zbyt
krótkim timeoucie pokazuje objaw diagnostyczny dopiero, gdy timeout jest
świadomie dobrany do klasy. Celowo krótki timeout ma dać czytelny błąd, nie
przypadkowe unieważnienie testu.

---

## Fallback do drugiego dostawcy

**Definicja.** **Fallback** — gdy główny dostawca (`a`) zawodzi, aplikacja
wysyła żądanie do zapasowego (`b`; w atrapie osobny endpoint z osobnymi
limitami). Kluczowa decyzja: co jest **awarią** (zerwane połączenie, 5xx,
timeout), a co **przeciążeniem** (529, 429), które fallback tylko przeniesie.

**Intuicja.** Zapasowy kurier: jeśli pierwszy nie przyjechał, dzwonisz po
drugiego. Ale jeśli za każdym razem najpierw czekasz godzinę na pierwszego —
paczka i tak wychodzi z godzinnym opóźnieniem.

**Po co to.** Ćw. 11: `a` milczy 30 s, read timeout 15 s, ruch 2/s × 40 s. Bez
dodatkowej logiki **każde** żądanie płaci 15 s u `a` + wywołanie u `b`:
p50 **19.8 s**, do `a` trafia 80 / 80. Fallback działa — ale latencję
wyznacza timeout martwego dostawcy, a jego sloty (i nasze) są zajęte przez
czekanie na nic.

**Częsta pomyłka.** Fallback „po cichu”. W ćw. 6 (pula połączeń za mała,
`PoolTimeout` jako `APITimeoutError`) fallback przerzucił na `b` 77 / 300
żądań — problem lokalny wyglądał jak sprawny system. Każdy fallback musi
zostawić ślad: atrybut na spanie, licznik per dostawca.

---

## Circuit breaker (wyłącznik)

**Definicja.** **Circuit breaker** to automat stanów przed zawodnym
zależnym systemem:
- **zamknięty** — ruch idzie normalnie, wyłącznik liczy kolejne awarie;
- **otwarty** — po *N* kolejnych awariach przez czas *T* żądania w ogóle nie
  idą do `a` (od razu fallback albo szybki błąd);
- **półotwarty** — po czasie *T* przepuszcza **jedno** żądanie-próbkę; sukces
  zamyka wyłącznik, porażka znów go otwiera.

W rozwiązaniu ćw. 11: N = 5, T = 30 s, stan widoczny jako atrybut `llm.cb.stan`
na spanie `llm.call`. 529 nie liczy się jako awaria.

**Intuicja.** Bezpiecznik w mieszkaniu: po zwarciu wyłącza obwód, żeby nie
spalić instalacji; po chwili ktoś próbuje włączyć jeden obwód — jeśli trzyma,
reszta wraca.

**Po co to.** Ten sam scenariusz z wyłącznikiem: p50 **7.7 s** (zamiast 19.8 s),
do `a` trafia **33 / 80** — wyłącznik otworzył się po 5 awariach, ale ~30
żądań było już w locie do `a` i i tak zapłaciło timeout. Wyłącznik skraca
czas trwania incydentu dla nowych żądań i daje dostawcy czas na podniesienie
się bez naszego ruchu.

**Częsta pomyłka.** Półotwarty stan przepuszczający cały ruch naraz — jeśli
`a` jeszcze nie wstał, wszystkie żądania znów płacą timeout, a jeśli wstał
ledwo — fala go dobija. Druga: wyłącznik liczący 429/529 jako awarie — zamknie
drogę do zdrowego, tylko przeciążonego dostawcy i przeniesie ruch tam, gdzie
też jest limit.

---

## Jak to się łączy (mapa)

```
 żądanie ──► deadline aplikacji per klasa (asyncio.timeout: 30 s / 330 s)       [ćw. 10]
               │  (k6 timeout i gunicorn MUSZĄ być dłuższe; sync 30 s zabija)    [ćw. 7, 10]
               ▼
            limiter tempa (RPM / ITPM / OTPM z nagłówków; 429 → pauza)            [ćw. 8]
               ▼
            JEDNA warstwa ponowień: backoff + pełny jitter + retry-after + budżet 20%   [ćw. 9]
               │  (SDK max_retries=0; timeoutów nie ponawiamy)
               ▼
            wyłącznik a: zamknięty → (5 awarii) → otwarty 30 s → półotwarty (1 próbka)  [ćw. 11]
               ├──► dostawca a ── read = bezczynność (stream: ping 15 s), 529 ≠ awaria
               └──► dostawca b (fallback, ślad w spanie i metrykach)
 amplifikacja = próby HTTP / żądania: bez kontroli 3.65, z budżetem 1.20
```

Teraz przejdź do ćw. 8.
