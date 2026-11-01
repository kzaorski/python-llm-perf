# Ćwiczenie 13: Streaming i TTFT — strumień, który klient dostaje na końcu

> Czas: ~40 min + mini-incydent IV ~20 min

> Blok IV. Czytanka `12a-backpressure-i-streaming.md` (TTFT, SSE, buforowanie, rozłączenie w strumieniu).

## Cel
Endpoint `POST /claims/{n}/reply/stream` odpowiada klientowi strumieniem SSE. Dostawca podaje pierwszy
token po ~0.5 s, metryka `llm_ttft_seconds` wygląda świetnie — a klient i tak czeka na pierwszy znak
tyle, ile trwa cała odpowiedź. Mierzysz TTFT **po stronie klienta**, znajdujesz miejsce, w którym
strumień jest buforowany, i naprawiasz je. Przy okazji: dlaczego k6 tego nie widzi.

## Teoria w pigułce
- **TTFT (time to first token)** — czas do pierwszego fragmentu odpowiedzi. Dla użytkownika czatu
  ważniejszy niż czas całkowity: od niego zależy, czy „coś się dzieje”. Pułapka: TTFT mierzony przy
  dostawcy (`llm_ttft_seconds`) ≠ TTFT u klienta — po drodze może być bufor, proxy, kompresja.
- **Buforowanie strumienia** — kod zbiera fragmenty do listy i wysyła na końcu (albo proxy/middleware
  czeka na całość). Klient dostaje strumień, ale z jednym zdarzeniem po całości. Objaw: TTFT klienta ≈ czas
  całkowity (100%).
- **Pułapka narzędzia: k6 i SSE.** `http_req_waiting` w k6 to czas do NAGŁÓWKÓW odpowiedzi.
  `StreamingResponse` wysyła nagłówki od razu, więc k6 pokazuje kilka ms niezależnie od buforowania.
  Mierz pierwszy fragment: metryka aplikacji `app_stream_first_chunk_seconds` albo klient, który czyta
  strumień (`scripts/strumien_ttft.py`).
- **Rozłączenie w trakcie strumienia** — Starlette (ASGI ≥ 2.4) nie przerwie generatora, gdy klient
  zniknie; trzeba co jakiś czas sprawdzić `request.is_disconnected()`, inaczej generacja trwa do końca
  (jak w ćw. 10).

## Kroki
1. Stan po ćw. 12, aplikacja na 8060. Zobacz strumień „gołym okiem” (`-N` wyłącza bufor curla):
   ```bash
   curl -sN -X POST 127.0.0.1:8060/claims/7/reply/stream | head -c 300; echo
   ```
2. **Hipoteza:** odpowiedź ma ~700 tokenów (~3 s generacji). Kiedy klient zobaczy pierwsze zdarzenie
   `delta`? Co pokaże k6 w `http_req_waiting`?
3. Pomiar od strony klienta i od strony k6:
   ```bash
   python scripts/strumien_ttft.py -n 20 -c 5
   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/strumien.js -e RATE=2 -e CZAS=30s
   ```
   U mnie: `strumien_ttft.py` — 20 strumieni: TTFT klienta p50 **2.76 s** (max 3.81 s), całość p50 2.76 s,
   **TTFT/całość 100%**; k6: `http_req_waiting` p50 **3 ms** (nagłówki), `klient_calosc` p50 2.69 s.
4. Prometheus — dwa TTFT obok siebie:
   ```
   histogram_quantile(0.5, sum by (le) (rate(app_stream_first_chunk_seconds_bucket[2m])))
   histogram_quantile(0.5, sum by (le) (rate(llm_ttft_seconds_bucket{klasa="krotkie"}[2m])))
   ```
   Pierwsze: kiedy aplikacja wysłała klientowi pierwszy fragment. Drugie: kiedy dostała go od dostawcy.
5. Otwórz **`app/strumien.py`** (`TODO ćw. 13`). Wysyłaj każdy fragment od razu (`yield sse("delta", …)`
   w pętli `async for`), wołaj `pierwszy_fragment(czasy, t0)` przy pierwszym fragmencie, a co ~20 fragmentów
   sprawdzaj `await request.is_disconnected()` i kończ (`wynik = "anulowane"`).
6. Restart, powtórka kroków 3–4. U mnie: `strumien_ttft.py` — TTFT klienta p50 **0.49 s** (max 0.74 s), całość
   p50 2.54 s, **TTFT/całość 19%**; k6 `http_req_waiting` bez zmian (2–3 ms) — k6 różnicy nie widzi.
   (Zapytanie z oknem `[2m]` tuż po przebiegu „przed” miesza oba — odczekaj 2 min.)

   U mnie (harness, 20 strumieni po 5 naraz): pierwszy fragment u klienta p50 **2.19 s = 100% całości** →
   **0.55 s = 19%** całości (2.89 s).
7. `python check.py ex13`

## Kryteria „done”
- [ ] Pierwsze zdarzenie `delta` dociera do klienta po < 30% czasu całej odpowiedzi.
- [ ] `app_stream_first_chunk_seconds` ≈ `llm_ttft_seconds` (różnica = czekanie na slot).
- [ ] Umiesz wyjaśnić, dlaczego k6 nie wykrył wady i czym ją mierzyć.
- [ ] `python check.py ex13` przechodzi.

## Pytania kontrolne
1. Po naprawie `app_stream_first_chunk_seconds` jest trochę większe niż `llm_ttft_seconds`. Z czego składa się różnica?
2. Między aplikacją a klientem stoi reverse proxy z buforowaniem odpowiedzi. Jak to wykryjesz tymi samymi narzędziami?
3. Strumień trwa 3 s, klient zamknął kartę po 0.5 s. Co dzieje się ze slotem i generacją przed i po naprawie?

Odpowiedzi: `solutions/pytania_odpowiedzi.md`.

## ★ Bonus (opcjonalnie)
Dopisz do `k6/strumien.js` pomiar pierwszego fragmentu przez moduł `k6/experimental/streams` albo
parsując `r.body` z timestampem z serwera (zdarzenie `koniec` niesie czasy). Czy da się to zrobić bez
zmiany serwera?

---

## Mini-incydent IV (po bloku IV) — „streszczenia wolne, kiedy działa dział analiz”

> ~20 min. Diagnoza przez `/diag`, `Server-Timing` i Prometheus; bez kodu.

Likwidatorzy skarżą się: zwykłe streszczenia raz trwają sekundę, a raz dostają 503 po kilku sekundach —
zawsze wtedy, gdy dział analiz zleca serię analiz dokumentacji.

1. Zatrzymaj własną aplikację i uruchom incydent:
   ```bash
   ./incydent.sh start mini-IV
   ```
2. Odtwórz: 40 analiz po 60 s w tle, a po 3 s jedno streszczenie:
   ```bash
   for i in $(seq 40); do curl -s -o /dev/null -X POST -H 'x-mock-total-s: 60' -H 'x-mock-ttft-ms: 500' 127.0.0.1:8060/claims/$i/analysis & done
   sleep 3
   curl -s -o /dev/null -w 'krótkie: %{http_code} po %{time_total} s\n' -X POST 127.0.0.1:8060/claims/1/summary
   curl -s 127.0.0.1:8060/diag | python -m json.tool | head -14
   ```
   ⟨MINI4⟩
3. Odpowiedz bez kodu: ile slotów zajmują długie, ile ma krótkie (`kolejka` w `/diag`,
   `llm_inflight` per klasa)? Czy limit kolejki i budżet czekania działają? Czego brakuje?
4. `python check.py ex12` — FAIL na incydencie. Potem `./incydent.sh stop` (zabija też analizy w toku).

Odpowiedź: `solutions/pytania_odpowiedzi.md`, sekcja „Mini-incydenty”.

---
Utknąłeś? `solutions/hints/ex13_hint1.md` → `hint2` → `hint3`. Gotowe rozwiązanie:
`solutions/ex13_strumien.py` → `app/strumien.py`.
