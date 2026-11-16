# 01a. Czytanka: teoria kolejek w praktyce

Czytanka, nie ćwiczenie — bez zadań i kryteriów „done”. Cel: przełożyć
prawo Little'a i krzywą wykorzystania z `00-teoria.md` na konkretne
czynności z bloku I: jak zmierzyć pojemność, jak znaleźć kolano na rampie,
ile slotów zaplanować i co się dzieje, gdy w jednej puli spotykają się
żądania sekundowe i wielominutowe. Każde pojęcie w schemacie:

> **Definicja** → **Intuicja/analogia** → **Po co to** → **Częsta pomyłka**

Wracaj tu, gdy coś przestanie się spinać. Krótkie definicje są w `slownik.md`.

---

## Pojemność i wąskie gardło

**Definicja.** **Pojemność** stacji to największa przepustowość, jaką może
utrzymać: **X_max = c / S** (c — liczba serwerów/slotów, S — średni czas
obsługi). Pojemność całej ścieżki żądania to **minimum** pojemności stacji, przez
które przechodzi — stacja, która wyznacza to minimum, to **wąskie gardło**.
Dla ścieżki streszczenia w kursie kandydatów jest kilka:

| Stacja | Pojemność | Przykład z kursu |
|---|---|---|
| semafor LLM | sloty / S | 4 / 1.06 s ≈ 3.8/s (szkielet), 32 / 1.06 s ≈ 30/s (po ćw. 6) |
| pula połączeń httpx2 | max_connections / S | 8 / 1.06 s ≈ 7.5/s przy semaforze 64 (wariant ćw. 6) |
| limit tokenów dostawcy | OTPM / tokeny_wyjścia | 12 000 / 200 = 60/min = 1/s (profil `limity`, ćw. 8) |
| moc dostawcy | generacje_naraz / S | 8 generacji + kolejka 8, potem 529 (profil `przeciazenie`, ćw. 9, 14) |
| procesy gunicorna `-k sync` | procesy / S | 29 / 3.5 s ≈ 8.3/s (ćw. 7) |
| pętla zdarzeń z blokadą | 1 / S | sync klient: 20 wywołań po 0.5 s = 10 s szeregowo (ćw. 4) |

**Intuicja.** Rura złożona z odcinków o różnych średnicach: przepływ wyznacza
najwęższy odcinek. Poszerzanie pozostałych nie zmienia nic — poza tym, że
przed najwęższym zbiera się więcej wody.

**Po co to.** Zanim dołożysz slotów, policz, czy to semafor jest wąskim
gardłem. W ćw. 8 aplikacja ma 32 sloty (30/s), ale profil `limity`
przepuszcza 1 streszczenie/s — dokładanie slotów zwiększy tylko liczbę 429.
W wariancie ćw. 6 semafor 64 przy puli połączeń 8 daje u dostawcy co najwyżej
8 generacji naraz — wąskim gardłem jest pula, nie semafor.

**Częsta pomyłka.** Liczenie pojemności z **czasu całkowitego** żądania
zamiast z **czasu obsługi** na danej stacji. Gdy żądanie czeka 30 s na slot i
1 s się wykonuje, slot jest zajęty 1 s, nie 31 s — do X_max = c / S wstawiasz
1.06 s. Odwrotnie dla puli wątków anyio: wątek jest zajęty przez cały czas
synchronicznego wywołania, łącznie z czekaniem na sieć.

---

## Wyznaczanie pojemności pomiarem: rampa

**Definicja.** **Rampa** to test otwarty, w którym intensywność dopływu
rośnie schodkami (w k6: executor `ramping-arrival-rate`, w kursie
`k6/rampa.js` z parametrami `OD`, `DO`, `SKOK`, `KROK_S`). Na każdym schodku
odczytujesz w oknie równym długości schodka: **osiągnięte tempo**, **zajętość**
zasobu (`llm_inflight`) i **czekanie** (p90 z histogramu
`llm_queue_wait_seconds`). Pojemność to tempo, na którym osiągnięta
przepustowość przestaje nadążać za zadaną.

**Intuicja.** Próba wysiłkowa na bieżni: prędkość rośnie co minutę, mierzysz
tętno. Długo rośnie liniowo, w pewnym momencie wypłaszcza się na maksimum —
dalej organizm „zaciąga dług” (kwas mlekowy = kolejka), którego nie widać
od razu w tempie biegu, tylko w tym, jak długo dochodzisz do siebie.

**Po co to.** Rampa po ćw. 6 (32 sloty, streszczenia ~1.06 s; zadane schodki
4, 12, 20, 28, 36, 44/s, każdy ~22 s) dała w kolejnych oknach 22 s z
Prometheusa (okna nie są idealnie wyrównane ze schodkami — `rate()` wygładza
przejścia):

| okno | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| osiągnięte tempo | 8 | 15 | 20.5 | 29.2 | 29.8 | 30.2/s |
| `llm_inflight` max | 13 | 24 | 31 | **32** | 32 | 32 |
| czekanie p90 | 0 | 0 | 0 | 1.6 s | 6.1 s | 9.7 s |

Trzy niezależne sygnały pokazują to samo: tempo staje na ~30/s, zajętość
przykleja się do 32, czekanie odrywa się od zera. Rachunek Little'a
(32 / 1.06 ≈ 30.2/s) zgadza się z pomiarem — model jest zweryfikowany i można
na nim planować.

**Częsta pomyłka.** Za krótkie schodki i ślepota na generator. Przy schodku
5 s kolejka nie zdąży urosnąć i kolano „przesunie się” w prawo. Powyżej
kolana generator też ma swoje limity: w rampie z kursu przy 36–44/s k6
zgłosił 130 `dropped_iterations` i 45 błędów `dial: i/o timeout` (sieć Docker
Desktop przy setkach nowych połączeń) — to są problemy **generatora**, nie
aplikacji, i podaje się je w raporcie osobno.

---

## Kolano krzywej: jak je wskazać

**Definicja.** **Kolano** to obszar wykorzystania, w którym czas czekania
przechodzi z „pomijalnego” w „rosnący szybciej niż obciążenie”. Praktyczna
definicja dla pomiaru: **najwyższe tempo, przy którym czekanie p90 (albo p99)
mieści się w budżecie**, np. ≤ 10% czasu obsługi. Teoretycznie (M/M/c) kolano
wypada tym bliżej ρ = 1, im więcej serwerów i im mniejsza zmienność czasów.

**Intuicja.** Na autostradzie przy 60% zajętości pasów jedziesz swobodnie,
przy 85% — falami, przy 95% — każde hamowanie jednego auta tworzy korek na
kilometr. Kolano to ten moment, gdy „fale” zaczynają się same z siebie.

**Po co to.** Dla 32 slotów rachunek Erlanga C (00-teoria) daje czekanie
średnio 0.03 s przy ρ = 0.8 (24/s), 0.15 s przy ρ = 0.9 (27/s), 3.1 s przy
ρ = 0.99 (30/s). Pomiar w rampie: czekanie p90 = 0 do ~20/s, 1.6 s przy
29.2/s. Kolano leży więc w okolicy **28–30/s** — ok. 90–97% pojemności
(30.2/s): przy wielu slotach i małej zmienności czasów obsługi jest blisko 100%.
Dla 4 slotów (szkielet) to samo ρ daje wielokrotnie dłuższe czekanie: mało
serwerów = łagodne, wczesne kolano.

**Częsta pomyłka.** Szukanie kolana na **średniej** latencji. Średnia rośnie
późno i łagodnie (dominuje ją masa żądań bez czekania); ogon (p90/p99
czekania) odrywa się wcześniej i wyraźniej. Druga pomyłka: kolano z wykresu
latencji całkowitej, gdy czas obsługi sam zmienia się z obciążeniem (np.
dostawca zwalnia pod ruchem) — wtedy rozdziel czekanie i obsługę.

---

## Planowanie pojemności z marginesem

**Definicja.** **Planowanie pojemności** to dobór liczby serwerów (slotów,
procesów, workerów) tak, żeby przy przewidywanym ruchu wykorzystanie
pozostało poniżej docelowego **ρ_cel** (zwykle 0.7–0.8):

> **c = ⌈ λ_szczyt · S / ρ_cel ⌉**

plus sprawdzenie, czy **każda** stacja na ścieżce (pula połączeń, limit
dostawcy, moc dostawcy) wytrzyma ten sam ruch.

**Intuicja.** Restauracja nie zatrudnia kelnerów na średni ruch z całego dnia,
tylko na sobotni wieczór — i trochę więcej, bo ktoś zachoruje.

**Po co to.** Przykład dla streszczeń: szczyt 20/s × 1.06 s = 21.2 slotu
średnio. Przy ρ_cel = 0.8: ⌈21.2 / 0.8⌉ = **27** slotów; przy 0.7 — **31**.
Wybór 32 slotów w kursie to ρ ≈ 0.66 przy 20/s. Margines pokrywa:
- **zmienność** — przybycia nie są równe, czasy obsługi mają ogon;
- **szczyty krótsze niż okno metryki** — „średnio 20/s” w minucie to może być
  40/s przez 10 s;
- **ponowienia** — każda próba to dodatkowe λ (ćw. 9: bez kontroli 3.65 próby
  na żądanie);
- **utratę instancji** — gdy jeden z dwóch procesów padnie, drugi dostaje
  podwójny ruch.

Druga połowa planu to **górne ograniczenia, których nie zmienisz slotami**:
limit dostawcy (OTPM 12 000 → 1 streszczenie/s w profilu `limity`), moc
dostawcy (8 generacji naraz w profilu `przeciazenie`). Sloty powyżej tego
sufitu nie zwiększą przepustowości — zwiększą 429/529.

**Częsta pomyłka.** „Dajmy 1000 slotów, będzie zapas”. Slot bez pokrycia w
pojemności następnej stacji przenosi kolejkę dalej, tam, gdzie gorzej ją
widać i gdzie płacisz błędami: u dostawcy (529, ćw. 14: 2 × 100
równoległych zadań na moc 8 → 179/200 błędów w 6 s). Limit współbieżności
**jest** narzędziem — ma odpowiadać pojemności tego, co jest za nim.

---

## Planowanie dla wywołań wielominutowych

**Definicja.** Ten sam wzór, ale S w minutach. Dla analiz (średnio ~153 s)
przy dopływie 0.4/s potrzeba średnio L = 0.4 × 153 ≈ 61 slotów, a z ρ_cel =
0.8 — **77**. To liczba trwających naraz wywołań u dostawcy, każde przez
minuty.

**Intuicja.** Parking: samochód na 5 minut i samochód na 5 godzin zajmują
tyle samo miejsca, ale ten drugi „konsumuje” go sześćdziesiąt razy więcej.

**Po co to.** Taki wynik zwykle oznacza, że synchroniczne trzymanie żądania
HTTP przez minuty jest złym modelem. Masz trzy opcje, wszystkie w kursie:
1. **Osobna pula dla długich** o rozmiarze zgodnym z mocą przeznaczoną dla
   nich (16 slotów → 0.105/s) i **jawne odrzucanie** nadmiaru (ćw. 12: 42
   szybkie 503 zamiast 30 porzuceń po minutach).
2. **Kolejka zadań** — klient dostaje identyfikator zadania od razu, worker
   przetwarza w swoim tempie, zaległość i jej wiek są widoczne (ćw. 14).
3. **Deadline per klasa** — krótkie 30 s, długie 330 s; żądanie, które i tak
   nie zdąży, nie zajmuje slotu (ćw. 10).

**Częsta pomyłka.** Wspólny deadline dla wszystkich klas. W teście z budowy
kursu deadline 150 s „ratował” medianę krótkich, ale zabił **wszystkie** 7
długich strumieni (120–300 s) — praca zmarnowana, slot u dostawcy zajęty na
nic.

---

## Ruch mieszany i head-of-line blocking

**Definicja.** **Head-of-line blocking** (blokowanie czoła kolejki) to sytuacja,
w której krótkie żądania czekają za długimi, bo dzielą tę samą kolejkę i te
same serwery. W puli c slotów wystarczy c długich żądań, żeby na czas ich
trwania pojemność dla krótkich spadła do zera. Wariancja czasów obsługi
dramatycznie wydłuża kolejkę przy tym samym średnim obciążeniu.

**Intuicja.** Jedna kolejka na poczcie: przed Tobą trzy osoby wysyłają po 40
paczek zagranicznych, Ty chcesz tylko kupić znaczek. Okienko „tylko listy”
(osobna pula) rozwiązuje problem bez dokładania pracowników.

**Po co to.** Dwa pomiary z kursu:
- **Semafor 8, ruch mieszany** (0.5/s przez 180 s: 75 krótkich ~2 s, 10 z
  długim TTFT 60–180 s, 7 z długim strumieniem 120–300 s): krótkie czekały
  **p50 85 s**, p99 113 s; opróżnienie trwało 240 s po końcu dopływu.
- **Wspólna pula 32** (ćw. 12: krótkie 4/s + długie 0.4/s, 180 s): krótkie
  czekanie **p50 29 s / p99 131 s**, w t = 180 s czeka 287 krótkich, drain
  342 s. **Osobne pule 32 / 16**: czekanie krótkich p99 = 0, całość p99 1.74 s.
  Długie wciąż się nie mieszczą — ale to już problem ich własnej pojemności, a
  nie krótkich.

Naprawy, od najprostszej: **osobne pule (bulkhead) per klasa**, **osobne
budżety czekania i deadline'y**, **przeniesienie długich do kolejki zadań**.
Priorytety we wspólnej kolejce pomagają mniej, niż się wydaje: gdy wszystkie
sloty zajęły długie, priorytet nie zwolni żadnego.

**Częsta pomyłka.** Diagnoza „krótkie są wolne, więc dostawca zwolnił”. Czas
obsługi krótkich (`llm_call_duration_seconds{klasa="krotkie"}`) jest w
porządku — rośnie tylko czekanie. Patrz na `llm_queue_wait_seconds` per
klasa i na `llm_inflight{klasa="dlugie"}`.

---

## Stan ustalony, rozgrzewka i opróżnianie

**Definicja.** **Stan ustalony** — okres, w którym średnie (tempo, zajętość,
czekanie) przestały się zmieniać. Pomiar pojemności ma sens tylko w nim. Przed
nim jest **rozgrzewka** (pule się zapełniają, połączenia się nawiązują), po
końcu dopływu — **opróżnianie**. Przy λ > X_max stanu ustalonego **nie ma**.

**Intuicja.** Nie mierzysz zużycia paliwa w pierwszych 30 sekundach po
odpaleniu zimnego silnika ani na zjeździe z autostrady.

**Po co to.** Z Little'a: stan ustalony przychodzi po czasie rzędu kilku W.
Dla streszczeń (W ~1 s) wystarczy kilka sekund; dla analiz (W ~150 s) —
**kilka minut**. Dlatego testy z długimi wywołaniami trwają w kursie ≥ 180 s
dopływu plus opróżnianie (razem 6.5–10 minut), a raport zawiera stan po końcu
dopływu: ilu czeka, wiek najstarszego, czas drain.

**Częsta pomyłka.** 60-sekundowy test z żądaniami trwającymi 150 s. Żadne
długie żądanie nie zdąży się skończyć w czasie dopływu, wszystkie wyniki
pochodzą z „ogona” po teście — a domyślny timeout k6 (60 s) i tak by je zerwał.

---

## Little jako test spójności pomiaru

**Definicja.** Mając dwa z trzech pomiarów (L, λ, W), liczysz trzeci i
porównujesz z jego niezależnym pomiarem. Rozbieżność = któryś pomiar jest zły
albo istnieje kolejka, której nie mierzysz.

**Intuicja.** Księgowość: przychody, rozchody i stan konta muszą się zgadzać.
Jeśli nie — gdzieś jest nieujęta faktura.

**Po co to.** Przykłady z kursu:
- kolejka zadań (ćw. 14): 2 procesy × 4 zadania = L = 8, 200 zadań w 28.7 s →
  X = 6.97/s → W = 8 / 6.97 ≈ 1.15 s na zadanie — zgodne z czasem streszczenia;
- gunicorn (ćw. 7): UvicornWorker 450 żądań, ostatnie po 34.6 s → osiągnięte
  450 / 34.6 = 13.0/s, choć zadane było 15/s — reszta to czekanie i ogon;
- wariant ćw. 6 z pulą połączeń 8: semafor przepuszcza 64, a u dostawcy
  `mock_llm_generating` ≤ 8 — Little dla dostawcy mówi, że ktoś trzyma resztę
  w kolejce przed nim; tą kolejką jest pula httpx2.

**Częsta pomyłka.** Porównanie średnich z różnych okien czasowych (λ z
minuty, W z całego testu). Okna muszą być te same.

---

## Jak to się łączy (mapa)

```
 pojemność stacji:  X_max = c / S          ścieżka: min(stacji) = wąskie gardło
        │                                    (semafor | pula połączeń | OTPM | moc dostawcy | procesy)
        ▼
 rampa (ćw. 3): tempo staje + inflight = c + czekanie p90 odrywa się  →  kolano ≈ 90–97% X_max (c = 32)
        │
        ▼
 plan: c = ⌈λ·S / ρ_cel⌉, ρ_cel 0.7–0.8  +  sprawdź sufity, których slotami nie podniesiesz
        │
        ├─ S w minutach → L w dziesiątkach → osobna pula + odrzucanie (ćw. 12) / kolejka zadań (ćw. 14)
        └─ ruch mieszany → head-of-line → osobne pule per klasa, deadline per klasa (ćw. 10, 12)
 kontrola: L = λ·W na każdej stacji; rozjazd = niemierzona kolejka
```

Teraz przejdź do ćw. 1.
