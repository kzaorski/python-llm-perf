# Ćwiczenie 5: Pula wątków anyio (40) — czekanie, które nie zużywa CPU

> Czas: ~30 min

> Blok II. Czytanka `04a-asyncio-petla-i-pule.md` (sekcja o puli wątków).

## Cel
Endpoint pism do klientów (`POST /claims/{n}/letter`) jest zwykłym `def` z synchronicznym klientem LLM.
FastAPI uruchamia takie handlery w puli wątków anyio, która ma limit **40**. Wysyłasz 60 pism naraz
i znajdujesz drugą „falę” — 20 żądań czeka na wolny wątek, choć procesor się nudzi, a dostawca ma
wolną moc. Naprawiasz handler tak, by nie zajmował wątku na czas czekania na LLM.

## Teoria w pigułce
- **Pula wątków anyio** — `def`-handlery FastAPI i `run_in_threadpool` wykonują się w wątkach roboczych
  z jednym globalnym limiterem: 40 naraz. Intuicja: 40 okienek; 41. klient czeka, aż ktoś odejdzie. Po co:
  chroni proces przed tysiącami wątków. Pułapka: wątek trzymany przez czekanie na sieć (LLM 2 s) to
  zmarnowane okienko — przepustowość = 40 / czas wywołania.
- **Czekanie bez CPU** — zasób (wątek) zajęty, procesor wolny. Profil CPU nic nie pokaże; to kolejka,
  nie obliczenia. Pułapka: „mamy wolny CPU, więc to nie aplikacja” — błędny wniosek.
- **Schodki w czasach odpowiedzi** — przy N > 40 czasy układają się w fale co ~czas wywołania:
  40 × t, potem 20 × 2t. Takie wielomodalne rozkłady są podpisem stałej puli. (→ `00-teoria.md`
  „Percentyle i ogon”)
- **`async def` + klient async** — na czas czekania na LLM korutyna oddaje pętlę i nie trzyma żadnego
  wątku. Limit współbieżności ustalasz wtedy świadomie (semafor slotów), a nie przypadkiem (40).

## Kroki
1. Stan po ćw. 4, aplikacja na 8060.
2. **Hipoteza:** 60 pism naraz, każde ~2.1 s u atrapy (nagłówek `x-mock-ttft-ms: 2000` ustala czas
   do pierwszego tokenu). Jaki będzie rozkład czasów? Ile żądań skończy się po ~2 s, ile później i kiedy?
3. Fala 60 równoległych żądań (posortowane czasy, w sekundach):
   ```bash
   seq 60 | xargs -P 60 -I{} curl -s -o /dev/null -w '%{time_total}\n' -X POST \
     -H 'x-mock-ttft-ms: 2000' -H 'x-mock-total-s: 0.1' 127.0.0.1:8060/claims/{}/letter | sort -n | awk '{printf "%.2f ", $1} END {print ""}'
   ```
   U mnie: 40 wartości 2.12–2.21 s, potem 20 wartości 4.19–4.33 s. Pierwsza fala zaraz po starcie
   procesu bywa wolniejsza (rozgrzewka klienta) — powtórz polecenie 2–3 razy.
4. Zobacz, czego NIE widać: `curl -s 127.0.0.1:8060/diag | python -m json.tool` — kolejka LLM pusta
   (pismo nie przechodzi przez semafor), lag pętli w normie (pętla nie stoi — stoją wątki). A CPU?
   Uruchom falę z kroku 3 jeszcze raz i w drugim terminalu, w jej trakcie:
   ```bash
   ps -o %cpu= -p $(lsof -tiTCP:8060 -sTCP:LISTEN)
   ```
   ⟨E05-CPU⟩
5. Otwórz **`app/szablony.py`** (`TODO ćw. 05`). Zamień handler na `async def` i wywołanie na
   asynchronicznego klienta aplikacji: `await klient.zapytaj(Zadanie(...))` z `app/llm/klient.py`.
   Renderowanie szablonu jest szybkie (mikrosekundy CPU) — może zostać w pętli.
6. Restart i powtórka kroku 3. U mnie: jedna fala, 60 × 2.14–2.28 s (p99 2.28 s; przed: 2.2 / 4.35 s).
7. `python check.py ex05`

## Kryteria „done”
- [ ] 60 równoległych pism kończy się jedną falą (max < 1.5 × min).
- [ ] Umiesz rozpoznać „schodki co ~40” w rozkładzie i wskazać ich przyczynę bez profilu.
- [ ] `python check.py ex05` przechodzi.

## Pytania kontrolne
1. Dlaczego objaw zaczyna się dokładnie od 41. żądania? Gdzie jest ta liczba?
2. Podniesienie limitu anyio do 400 też „naprawi” test. Jaki problem przenosisz w ten sposób dalej?
3. Czym różni się ten objaw od ćw. 4 (blokada pętli)? Jak rozróżnisz je po `/diag/ping`?

Odpowiedzi: `solutions/pytania_odpowiedzi.md`.

## ★ Bonus (opcjonalnie)
Wyślij 60 pism i równolegle 20 klasyfikacji (już async po ćw. 4). Czy klasyfikacje czekają na pisma?
Dlaczego nie? A co by było, gdyby i pisma, i klasyfikacje były `def`?

---
Utknąłeś? `solutions/hints/ex05_hint1.md` → `hint2` → `hint3`. Gotowe rozwiązanie:
`solutions/ex05_szablony.py` → `app/szablony.py`.
