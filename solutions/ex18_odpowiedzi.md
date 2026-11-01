# Ćw. 18 — klucz odpowiedzi: incydent „w poniedziałek rano wszystko zwolniło”

> Czytaj dopiero po napisaniu własnego raportu.

`./incydent.sh start final` uruchamia aplikację w stanie po ćw. 17 z czterema przywróconymi usterkami:
jedną konfiguracyjną (`LLM_SLOTY=4`) i trzema w kodzie. Dodatkowo `FAQ_TTL_S=30` (krótszy TTL cache — nie jest
usterką, tylko skraca okres, w którym stampede się powtarza, żeby był widoczny w 4-minutowym teście).

Ruch (`./incydent.sh ruch`, k6 `incydent.js`, 240 s, model otwarty): streszczenia 8/s, odpowiedzi strumieniem
1/s, FAQ 5/s (5 pytań), analizy 6/min (klient rezygnuje po 30 s). Liczby poniżej: ten sam ruch na incydencie i
na stanie wzorcowym (`./incydent.sh start własny 17`), sygnały z Prometheusa w oknie przebiegu,
`dropped_iterations` = 0 w obu.

## Usterki — objaw → ślad → przyczyna → naprawa

### 1. Za mało slotów LLM (konfiguracja `LLM_SLOTY=4`) — ćw. 06
- **Objaw:** streszczenia wolne albo 503 po ~5 s; u klienta (k6) 1406 × 503 obok 1619 × 200.
- **Ślad:** `max(llm_inflight{klasa="krotkie"})` = **4** (wzorzec: 17); czekanie na slot p50 **3.99 s** (ucięte
  budżetem czekania 5 s; wzorzec 0.003 s); `sum by (wynik) (increase(app_requests_total{endpoint="summary"}[5m]))`
  → `odrzucone` **≈1586** (wzorzec 0; k6 policzył 1406 × 503 dla streszczeń — `increase()` ekstrapoluje na
  granicach okna i liczy wszystkie odrzucone krótkie, więc liczby się nie pokrywają, rząd wielkości ten sam). Dostawca niedociążony: `max(mock_llm_generating)` = 16, z czego 12 to analizy
  (wzorzec 19). Trace: długi `llm.queue_wait` obok krótkiego `llm.call` (`{span.llm.queue.wait_ms > 100.0}`).
- **Przyczyna:** L = λ·W = 8/s × ~1 s ≈ 8 + FAQ + strumień ≫ 4 slotów. Odrzucenia to poprawna reakcja
  ograniczonej kolejki (ćw. 12) na brak pojemności — nie usterka backpressure.
- **Naprawa:** sloty z Little'a (32 dla krótkich, ćw. 06) — usunąć nadpisanie `LLM_SLOTY`. Dowód: sonda `check.py ex06`.
- **Pułapka diagnozy:** 503 kuszą, by „podnieść limit kolejki”. Odróżnia je `llm_inflight` przyklejone do 4 przy
  wolnej mocy dostawcy (przy poprawnych slotach 503 pojawiłyby się dopiero przy `mock_llm_generating` ≈ moc).

### 2. Strumień buforowany w całości (W9) — ćw. 13
- **Objaw:** odpowiedzi strumieniem „pojawiają się naraz po kilku sekundach”; k6 `http_req_waiting` niski
  (nagłówki od razu) — raport k6 wygląda dobrze.
- **Ślad:** `histogram_quantile(0.5, sum by (le) (rate(app_stream_first_chunk_seconds_bucket[5m])))` = **8.07 s** vs
  `llm_ttft_seconds` p50 **0.63 s** (wzorzec: 0.48 s vs 0.48 s). Część z 8 s to czekanie na slot (usterka 1),
  ale różnica pierwszy fragment ≫ TTFT dostawcy + czekanie zostaje — `scripts/strumien_ttft.py`: pierwszy
  fragment ≈ 100% czasu całości.
- **Przyczyna:** generator zbiera fragmenty i wysyła je po zakończeniu generacji.
- **Naprawa:** `yield` każdego fragmentu od razu + sprawdzanie rozłączenia (ćw. 13). Dowód: sonda `check.py ex13`.

### 3. Cache FAQ bez single-flight — stampede (W10) — ćw. 15
- **Objaw:** FAQ wolne co ~30 s, dostawca dostaje fale identycznych pytań.
- **Ślad:** `sum by (wynik) (increase(app_cache_total[5m]))` → `miss` **290** przy 5 pytaniach i TTL 30 s (potrzeba
  ≈ 5 × 240/30 = 40); wywołań LLM dla FAQ **295**; brak `wspolne` (wzorzec: 36 miss / 36 wywołań + 36 „wspolne”).
  Test celowany: 50 identycznych nowych pytań → 50 wywołań LLM.
- **Przyczyna:** każde chybienie samo woła LLM; nie ma mechanizmu „ktoś już liczy ten klucz”.
- **Naprawa:** single-flight (`Future` w procesie + `SET NX PX` w Redisie, ćw. 15). Dowód: sonda `check.py ex15`.

### 4. Brak anulowania po rozłączeniu klienta (W16) — ćw. 10
- **Objaw:** po zakończeniu ruchu system „jeszcze długo coś robi”; dostawca generuje analizy, na które nikt nie
  czeka (klient analiz rezygnuje po 30 s).
- **Ślad:** `sum by (phase) (increase(mock_llm_cancelled_total[10m]))` = **0** mimo porzuceń po stronie k6
  (wzorzec: 24); `max(llm_inflight{klasa="dlugie"})` = **13** (wzorzec 4); `mock_llm_generating` spada do 0 dopiero
  **125 s** po końcu ruchu (wzorzec 32 s); `/admin/stats` → `generating` > 0, `oldest_inflight_s` rośnie po końcu.
- **Przyczyna:** wywołanie nie jest anulowane, gdy klient się rozłączy — trzyma slot aplikacji i slot dostawcy do
  końca generacji (minuty).
- **Naprawa:** strażnik `request.is_disconnected()` + anulowanie pracy, deadline per klasa (ćw. 10). Dowód: sonda
  `check.py ex10`.

## Interakcje między usterkami (sprawdzone pomiarem)
- **1 wzmacnia 3:** dłuższe czekanie na slot wydłuża okno chybienia — wszystkie żądania FAQ, które przyszły,
  zanim pierwsze skończyło, też widzą „miss”. Dlatego 290 chybień zamiast ~40.
- **1 zawyża objaw 2:** pierwszy fragment strumienia zawiera czekanie na slot; dlatego porównuj z `llm_ttft_seconds`
  i czekaniem, a nie z „normą” z ćw. 13.
- **4 zabiera sloty długim na długo**, ale nie krótkim — pule są osobne (ćw. 12); gdyby nie były, usterka 4
  pogłębiłaby usterkę 1.

## Co należało wykluczyć (i czym)
- Burza ponowień i limity dostawcy: przyrost odpowiedzi atrapy w czasie incydentu to wyłącznie 200 (u mnie 836) —
  zero 429/529, więc nie ma czego ponawiać (przy 4 slotach dostawca jest niedociążony). Sprawdzasz:
  `curl -s 127.0.0.1:8061/admin/stats` i `sum by (status) (increase(llm_http_responses_total[5m]))`.
- Blokada pętli / pula wątków: `/diag/ping` i `app_event_loop_lag_seconds` — w tym incydencie nie są źródłem
  problemu (sprawdź liczbą; w moim przebiegu nie mierzyłem ich osobno, więc tu nie podaję wartości).
- Kolejka bez limitu: kolejka krótkich jest ograniczona (w chwili końca dopływu 45 czeka, najstarsze 4.9 s —
  budżet 5 s), szybkie 503 — to objaw usterki 1, nie brak backpressure.
- `status 0` w k6: 96 krótkich (wzorzec 122) = `dial: i/o timeout` sieci Docker Desktop przy setkach nowych
  połączeń (aplikacja ich nie zarejestrowała; występują w obu wariantach); 25 długich = zamierzone porzucenia po 30 s.

## Rubryka samooceny
| Poziom | Kryterium |
|---|---|
| ⭐ | Wskazane ≥ 2 usterki z poprawną przyczyną, choć bez liczb lub z sygnałem ogólnym („p99 wysokie”). |
| ⭐⭐ | Wszystkie 4 usterki z sygnałem specyficznym i liczbą; naprawa wskazana na poziomie mechanizmu. |
| ⭐⭐⭐ | Jak wyżej + co najmniej 2 udokumentowane wykluczenia + jedna interakcja (np. 1 → 3) wyjaśniona i poparta liczbą; poprawna interpretacja 503 (usterka 1, nie backpressure) i `status 0` (sieć Dockera). |
| ⭐⭐⭐⭐ | Jak wyżej + porównanie z przebiegiem na stanie wzorcowym w jednej tabeli i alerty PromQL (bonus), które odpalają na incydencie, a nie na wzorcu. |
