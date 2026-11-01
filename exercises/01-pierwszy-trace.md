# Ćwiczenie 1: Pierwszy trace — gdzie żądanie czeka, a gdzie pracuje

> Czas: ~45 min (w tym ~15 min na pierwsze uruchomienie stosu)

> Blok I — Pomiar i teoria kolejek (ćw. 1–3). Zanim zaczniesz, przeczytaj `00-teoria.md`
> (przynajmniej „Czekanie vs obsługa” i „Jak czytać trace, metryki i profil w tym kursie”).
> Czytanka bloku: `01a-teoria-kolejek-w-praktyce.md`.

## Cel
Uruchamiasz aplikację „asystenta likwidatora szkód”, oglądasz trace jednego streszczenia
zgłoszenia i dopisujesz brakujący pomiar: **czas czekania na slot LLM**. Po ćwiczeniu każdy trace
pokazuje osobno czekanie (span `llm.queue_wait`) i obsługę (span `llm.call`), a Prometheus ma
histogram czekania. Na tym pomiarze stoją wszystkie kolejne ćwiczenia.

## Teoria w pigułce
- **Czas odpowiedzi = czekanie + obsługa.** Obsługa to praca wykonywana dla żądania (tu: wywołanie
  LLM), czekanie to stanie w kolejce przed nią (tu: na wolny slot semafora). Intuicja: kolejka do
  kasy — kasjerka obsługuje Cię 1 min, ale przy kasie stoisz 10. Po co: pod obciążeniem prawie cały
  wzrost latencji to czekanie, a nie wolniejsza obsługa. Pułapka: czekania nie widać w trace, jeśli
  nikt go nie zmierzył — wygląda jak „pusta przerwa” albo doliczasz je do obsługi.
  (→ `00-teoria.md` „Czekanie vs obsługa”)
- **Semafor (slot)** — licznik pozwoleń: najwyżej N wywołań LLM naraz, reszta czeka na
  `acquire()`. Po co: chroni dostawcę i nasz budżet przed zalewem. Pułapka: semafor jest kolejką
  bez okienka — nie raportuje, ile osób czeka ani jak długo, dopóki tego nie dopiszesz.
- **Span-rodzeństwo vs span-rodzic** — czekanie i wywołanie następują PO SOBIE, więc są
  rodzeństwem pod spanem żądania. Gdyby `llm.queue_wait` był rodzicem `llm.call`, trace mówiłby
  „wywołanie było częścią czekania” — fałsz, który psuje każdą późniejszą analizę.
- **RED** (Rate, Errors, Duration) — trzy pytania o każdą usługę: ile żądań/s, ile błędów, jak długo.
  W tym kursie: `app_requests_total{endpoint,wynik}` i `app_request_duration_seconds`.
  (→ `00-teoria.md` „RED i USE dla tej aplikacji”)

## Kroki
1. **Stos i środowisko** (raz na cały kurs):
   ```bash
   docker compose up -d --wait                       # lgtm, redis, mock-llm (projekt llmperf)
   python -m venv .venv && .venv/bin/pip install -r requirements.txt
   source .venv/bin/activate
   python scripts/generuj_zgloszenia.py              # data/zgloszenia.jsonl (20 000 zgłoszeń)
   ```
2. **Aplikacja** (terminal T1; zostaw ją uruchomioną):
   ```bash
   uvicorn app.main:app --port 8060
   ```
   T2: `curl -s 127.0.0.1:8060/health` — `"status": "ok"`, zależności `redis` i `llm` (atrapa) OK.
3. Jedno streszczenie, z nagłówkami:
   ```bash
   curl -s -D - -X POST 127.0.0.1:8060/claims/42/summary | grep -iE 'server-timing|^\{'
   ```
   `Server-Timing` niesie czasy w ms: `czekanie`, `llm`, `total`. Teraz `czekanie` jest bliskie 0.
4. **Zanim spojrzysz w trace:** ile spanów spodziewasz się w trace jednego streszczenia i w jakiej
   relacji (kto jest czyim rodzicem)? Gdzie w nim będzie widać czekanie na slot?
5. Grafana http://127.0.0.1:3060 (admin/admin) → **Explore → Tempo → TraceQL**:
   ```
   {resource.service.name="claims-assistant" && name="POST /claims/{n}/summary"}
   ```
   Otwórz najnowszy trace. Zobaczysz łańcuch `POST /claims/{n}/summary` → `llm.call` →
   `anthropic.messages.create` (span natywny SDK) → `POST` (klient HTTP httpx2) + drobne `http send`.
   Czekania nie ma — przy jednym żądaniu go zresztą nie było.
6. **Hipoteza:** aplikacja ma 4 sloty LLM, streszczenie trwa ~1 s. Co się stanie z 40 żądaniami naraz?
   Ile będzie trwało ostatnie? Czy trace to pokaże?
   ```bash
   for i in $(seq 1 40); do curl -s -o /dev/null -X POST 127.0.0.1:8060/claims/$i/summary & done; wait
   ```
   W Tempo wybierz trace o największym czasie: span żądania trwa kilka sekund, a `llm.call`
   zaczyna się dopiero pod koniec. Przed nim — dziura. To czekanie na semafor, niewidoczne.
7. Otwórz **`app/llm/limiter.py`**, funkcja `slot()`, miejsce `TODO ćw. 01`. Dopisz trzy rzeczy:
   - span `llm.queue_wait` od chwili `t0_ns` do teraz — utworzony **bez aktywowania** (rodzeństwo
     `llm.call`, nie jego rodzic) i od razu zamknięty,
   - atrybut `llm.queue.wait_ms` na spanie żądania (`trace.get_current_span()`),
   - punkt histogramu `telemetry.H_CZEKANIE` z atrybutem `klasa` (przez `telemetry.zapisz`).
8. Zrestartuj aplikację (Ctrl+C w T1, ponownie `uvicorn …`) i powtórz pętlę z kroku 6. W Tempo:
   ```
   {name="llm.queue_wait"}
   {span.llm.queue.wait_ms > 100.0}
   ```
   Drugie zapytanie zwraca żądania, które czekały dłużej niż 100 ms (atrybut jest liczbą zmiennoprzecinkową —
   TraceQL porównuje typy, więc `> 100` bez `.0` nie zwróci nic) — w trace dziura jest teraz
   spanem `llm.queue_wait`, a obok niego (nie pod nim) leży `llm.call`.
9. **Explore → Prometheus** (RED + czekanie; metryki wysyłane co 5 s — odczekaj chwilę):
   ```
   sum by (endpoint, wynik) (rate(app_requests_total[1m]))
   histogram_quantile(0.99, sum by (le, endpoint) (rate(app_request_duration_seconds_bucket[1m])))
   histogram_quantile(0.99, sum by (le, klasa) (rate(llm_queue_wait_seconds_bucket[1m])))
   ```
   Porównaj p99 czasu żądania z p99 czekania: jaka część latencji to kolejka?
10. `python check.py ex01`

## Kryteria „done”
- [ ] Trace streszczenia zawiera span `llm.queue_wait` jako **rodzeństwo** `llm.call` i atrybut
      `llm.queue.wait_ms` na spanie żądania.
- [ ] W Prometheusie jest `llm_queue_wait_seconds_bucket{klasa="krotkie"}`.
- [ ] Po pętli 40 żądań umiesz powiedzieć, ile z czasu najwolniejszego żądania to czekanie, a ile LLM.
- [ ] `python check.py ex01` przechodzi.

## Pytania kontrolne
1. Dlaczego span czekania tworzysz przez `start_span` (bez aktywacji), a nie `start_as_current_span`?
   Co by pokazał trace w drugim przypadku?
2. Przy 40 żądaniach i 4 slotach po ~1 s: ile mniej więcej czekało ostatnie żądanie? Z czego to wynika?
3. Nagłówek `Server-Timing` i trace pokazują ten sam podział. Po co Ci oba (kto czyta który)?

Odpowiedzi: `solutions/pytania_odpowiedzi.md` (zajrzyj PO własnej próbie).

## ★ Bonus (opcjonalnie)
Dodaj do spanu `llm.queue_wait` atrybut z liczbą żądań czekających w chwili wejścia do kolejki
(`st.liczba_czekajacych`). Znajdź TraceQL-em żądania, które zastały kolejkę dłuższą niż 20, i porównaj
ich czekanie z prawem Little'a (ćw. 3).

---
Utknąłeś? Stopniowane podpowiedzi: `solutions/hints/ex01_hint1.md` (kierunek) →
`hint2` (API OTel) → `hint3` (pseudokod). Gotowe rozwiązanie to OSTATNI szczebel:
`solutions/ex01_limiter.py` → `app/llm/limiter.py`.
