# Ćwiczenie 18: Finał — incydent „w poniedziałek rano wszystko zwolniło”

> Czas: ~90 min: ruch incydentu ~4 min + opróżnianie do ~2.5 min (puszczasz go 2–3 razy), diagnoza, raport,
> naprawa i porównanie z ruchem na stanie naprawionym (kolejne ~6 min).

> Blok V — zamknięcie kursu. Przed startem przejrzyj `00-teoria.md` „USE i RED” oraz notatki z mini-incydentów.

## Cel
Po wdrożeniu „drobnych poprawek konfiguracji i porządków w kodzie” asystent biura szkód działa źle na wielu
frontach naraz. Twoje zadanie to zdiagnozować incydent **bez czytania kodu** — tylko z telemetrii (Tempo,
Prometheus, Pyroscope), `/diag`, `/admin/stats` atrapy i nagłówków `Server-Timing` — i dla każdej usterki
napisać łańcuch: **objaw → ślad (gdzie i jaka liczba) → przyczyna → naprawa**. W incydencie jest kilka
niezależnych usterek; każda ma własny, rozróżnialny sygnał (sprawdzone pomiarem na tym samym ruchu).

## Teoria w pigułce
- **Kilka wad naraz** — objawy się nakładają: jedna wada może wydłużyć okno innej (np. dłuższe czekanie →
  szersze okno chybień cache), a wspólny objaw (wolne odpowiedzi, 503) ma wiele możliwych przyczyn. Szukaj
  sygnału **specyficznego** dla mechanizmu, nie ogólnego „p99 wysoko”.
- **Metoda** — RED per endpoint (który endpoint cierpi i jak: tempo, błędy wg `wynik`, czas) → USE zasobów
  (sloty: `llm_inflight`/`llm_waiting`; dostawca: `mock_llm_generating`, `mock_llm_cancelled_total`) →
  ślady konkretnych żądań (gdzie leży czas) → hipoteza → test hipotezy jednym celowanym poleceniem.
- **Zaległość po ruchu** — co dzieje się PO końcu dopływu (ćw. 10, 12): czy sloty i dostawca wracają do zera,
  i po ilu sekundach.
- Pułapka pomiaru: `status 0` w k6 przy setkach nowych połączeń z kontenera do `host.docker.internal` to
  zwykle `dial: i/o timeout` sieci Docker Desktop, nie odpowiedź aplikacji (aplikacja ich nie rejestruje) —
  licz je osobno. Analizy w tym ruchu celowo rezygnują po 30 s (klient z krótkim limitem).

## Kroki
1. Zatrzymaj własną aplikację (Ctrl+C) i worker kolejki, jeśli działa. Start incydentu:
   ```bash
   ./incydent.sh start final
   curl -s 127.0.0.1:8060/health
   ```
2. **Hipoteza wstępna:** z opisu („drobne poprawki konfiguracji i porządki w kodzie”) zapisz trzy rzeczy, które
   sprawdzisz najpierw, i metrykę dla każdej.
3. Ruch incydentu (model otwarty, ~4 min: streszczenia 8/s, odpowiedzi strumieniem 1/s, FAQ 5/s — 5 popularnych
   pytań, analizy 6/min z klientem rezygnującym po 30 s). k6 czeka po końcu dopływu do 150 s na żądania w toku:
   ```bash
   ./incydent.sh ruch
   ```
   **W trakcie** (Grafana → Explore → Prometheus, „Last 15 minutes”) obserwuj co najmniej:
   ```
   sum by (endpoint, wynik) (rate(app_requests_total[1m]))
   max by (klasa) (llm_inflight)
   max by (klasa) (llm_waiting)
   max(mock_llm_generating)
   ```
   **Po końcu dopływu:** czy `llm_inflight{klasa="dlugie"}` i `mock_llm_generating` spadają do 0 od razu?
4. Diagnoza — dla każdego obszaru poszukaj sygnału i zapisz liczbę (nie ma tu podpowiedzi, które wady są w środku):
   - czekanie na slot vs czas wywołania (ćw. 01, 03, 06): histogram `llm_queue_wait_seconds` per klasa, ślady
     z `llm.queue.wait_ms > 100`;
   - strumień od strony klienta vs od strony dostawcy (ćw. 13): `app_stream_first_chunk_seconds` vs `llm_ttft_seconds`;
   - FAQ i cache (ćw. 15): `sum by (wynik) (increase(app_cache_total[5m]))` a liczba wywołań LLM dla FAQ;
   - porzucone żądania i praca „do nikogo” (ćw. 10, 12): `sum by (phase) (increase(mock_llm_cancelled_total[10m]))`,
     `curl -s 127.0.0.1:8061/admin/stats`, `curl -s 127.0.0.1:8060/diag`;
   - ponowienia, limity, wyłącznik, pętla zdarzeń — wyklucz je liczbą (np. `llm_http_attempts_total` /
     żądania, `app_event_loop_lag_seconds`), a nie domysłem.
   Hipotezy weryfikuj celowanymi poleceniami z ćwiczeń (np. 50 identycznych pytań FAQ z ćw. 15,
   `python scripts/strumien_ttft.py -n 20 -c 5` z ćw. 13) — w trakcie incydentu, bez czytania kodu.
5. `python check.py ex18` — na incydencie FAIL z liczbą dla każdej niespełnionej sondy (sondy ćwiczeń, których
   dotyczą usterki). Zapisz komunikaty — to dodatkowe potwierdzenie Twojej diagnozy, nie jej zastępstwo.
6. **Raport** (w pliku tekstowym, dla każdej usterki): objaw → ślad (metryka/zapytanie + liczba, ślad w Tempo) →
   przyczyna (mechanizm, nie nazwa pliku) → naprawa (co zmienić i jakim poleceniem udowodnisz, że pomogło).
   Dodaj: co wykluczyłeś i na jakiej podstawie; jak usterki wpływają na siebie nawzajem.
7. **Naprawa i dowód.** `./incydent.sh stop`, uruchom **własną** aplikację (stan po ćw. 17, z Twoimi poprawkami
   i bez „poprawek konfiguracji” z incydentu), potem:
   ```bash
   python check.py ex18
   ```
   PASS = żadna z usterek incydentu nie występuje w Twojej wersji. Dla porównania liczb puść ten sam ruch na
   stanie wzorcowym: `./incydent.sh start własny 17 && ./incydent.sh ruch`, potem `./incydent.sh stop`
   i zestaw obie serie sygnałów w jednej tabeli.
8. Porównaj raport z `solutions/ex18_odpowiedzi.md` i oceń się rubryką na końcu tego pliku.

## Kryteria „done”
- [ ] Raport wskazuje każdą usterkę incydentu z rozróżnialnym sygnałem (liczba z Prometheusa/Tempo/atrapy) i
      przyczyną na poziomie mechanizmu.
- [ ] Dla co najmniej dwóch obszarów masz udokumentowane wykluczenie (np. „burzy ponowień nie ma, bo …”).
- [ ] Umiesz wskazać jedną parę usterek, które wzmacniają nawzajem swoje objawy, i wyjaśnić dlaczego.
- [ ] `python check.py ex18`: FAIL na incydencie, PASS na Twojej aplikacji.

## Pytania kontrolne
1. Część streszczeń dostała 503 po ~5 s, choć dostawca był niedociążony. Jak odróżnisz „kolejka ma limit i działa
   poprawnie” od „za mało slotów”? Którą metrykę pokażesz zespołowi?
2. Dlaczego raport k6 (`http_req_waiting`) nie wskazał problemu ze strumieniem?
3. Po końcu dopływu atrapa generowała jeszcze ~2 minuty. Kto płaci za tę pracę i jak to wykazać liczbą?

Odpowiedzi: `solutions/pytania_odpowiedzi.md` i `solutions/ex18_odpowiedzi.md` (pełny klucz + rubryka).

## ★ Bonus (opcjonalnie)
Napisz alerty (PromQL), które wykryłyby każdą z usterek w ciągu 5 minut od wdrożenia — bez fałszywych alarmów
na stanie wzorcowym. Sprawdź je na obu przebiegach z kroku 7.

---
Utknąłeś? `solutions/hints/ex18_hint1.md` → `hint2` → `hint3`. Pełny klucz: `solutions/ex18_odpowiedzi.md`
(dopiero po napisaniu własnego raportu).
