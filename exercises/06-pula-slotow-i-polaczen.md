# Ćwiczenie 6: Za mało slotów, za mała pula połączeń — czekanie na zasób, którego nie widać

> Czas: ~45 min (trzy przebiegi ruchu otwartego po 15 s; pierwszy opróżnia się ~1.5 min)

> Blok II. Czytanka `04a-asyncio-petla-i-pule.md` (semafor, pula połączeń httpx2); `00-teoria.md`
> „Prawo Little'a”.

## Cel
Aplikacja ma 4 sloty LLM, a ruch docelowy to ~20 streszczeń/s. Mierzysz skutki pod obciążeniem
(czekanie na slot ≫ czas wywołania, niedociążony dostawca), dobierasz liczbę slotów z prawa Little'a
i ustawiasz ją w kodzie. Potem drugi, podstępniejszy wariant: semafor duży, ale **pula połączeń HTTP**
klienta mniejsza — czekanie przenosi się tam, gdzie Twój pomiar go nie widzi, a z krótkim
`pool timeout` zamienia się w błędy.

## Teoria w pigułce
- **Za mały zasób = kolejka przed nim.** Przy λ = 20/s i W ≈ 1.06 s w toku powinno być L ≈ 21 wywołań.
  Przy 4 slotach pojemność to ~3.8/s — nadwyżka 16/s czeka i kolejka rośnie liniowo w czasie dopływu.
  Pułapka: dostawca wygląda na zdrowego i niedociążonego; „wolny LLM” to w rzeczywistości nasza kolejka.
- **Pula połączeń httpx2** — klient HTTP SDK trzyma najwyżej `max_connections` połączeń na dostawcę.
  Wywołanie, które nie dostało połączenia, czeka w puli do `pool timeout`. Domyślnie w SDK: 1000
  połączeń i `pool=600 s`. Pułapka: przy puli mniejszej niż semafor czekanie dzieje się WEWNĄTRZ
  `llm.call` — wygląda jak wolny dostawca, a span `llm.queue_wait` pokazuje 0.
- **PoolTimeout** — po przekroczeniu `pool timeout` httpx2 rzuca `PoolTimeout`, który SDK opakowuje jako
  `anthropic.APITimeoutError`. Pułapka: z włączonym fallbackiem (ćw. 11) taki „timeout” po cichu
  przerzuca ruch do zapasowego dostawcy — zamiast alarmu masz nieoczekiwany koszt i ruch u `b`.
- **Rozmiar puli = Little + zapas, nie „więcej = lepiej”.** Sloty ponad moc/limity dostawcy przenoszą
  kolejkę do niego (429, 529 — ćw. 8–9). Suma slotów wszystkich procesów ≤ moc dostawcy.

## Kroki
1. Stan po ćw. 5, aplikacja na 8060 (4 sloty). Rachunek z ćw. 3: ile slotów na 20/s?
2. **Hipoteza:** ruch otwarty 20/s przez 15 s (300 żądań). Ile wyniesie czekanie p99? Kiedy przyjdzie
   ostatnia odpowiedź? Ile generacji naraz zobaczy atrapa (`mock_llm_generating`)?
3. Ruch (Twój `k6/otwarty.js` z ćw. 2):
   ```bash
   docker compose run --rm -e WYNIK=ex06-przed k6 run -o experimental-prometheus-rw /scripts/otwarty.js -e RATE=20 -e CZAS=15s
   ```
   W trakcie: `curl -s 127.0.0.1:8060/diag | python -m json.tool` — `kolejka.krotkie.czekajace` i
   `wiek_najstarszego_s` rosną, `w_toku` = 4. U mnie: 277 × 200, test 74.3 s przy 15 s dopływu, k6 pominął
   24 iteracje (`dropped_iterations` — wszystkie 200 wstępnie przydzielonych VU czekały, a dokładanie nowych nie
   nadążyło; przy tak zatkanym systemie to i tak niedoszacowanie kolejki); czekanie p50 30.0 / p99 **57.4 s**
   przy LLM p50 1.04 s; `llm_waiting` max 213, `mock_llm_generating` max **4**.
4. Grafana → Prometheus (USE dla slotów i dla dostawcy):
   ```
   max_over_time(llm_inflight{klasa="krotkie"}[2m])
   max_over_time(llm_waiting{klasa="krotkie"}[2m])
   max_over_time(mock_llm_generating{provider="a"}[2m])
   histogram_quantile(0.99, sum by (le) (rate(llm_queue_wait_seconds_bucket{klasa="krotkie"}[2m])))
   ```
   Sloty nasycone (4), kolejka setek żądań, a dostawca o mocy 64 generuje 4 naraz.
5. Otwórz **`app/llm/limiter.py`**: `SLOTY = int(os.environ.get("LLM_SLOTY", "4"))`. Ustaw domyślną
   wartość z rachunku (L = λ·W + zapas na ogon; ja wziąłem 32) i zapisz w komentarzu, skąd się wzięła.
6. Restart, powtórka kroku 3 z `-e WYNIK=ex06-po`. U mnie: 301 × 200 w 16.2 s (18.6/s), czekanie p99 **0 ms**,
   LLM p50 1.03 / p99 1.74 s.

   U mnie (harness, ten sam ruch 20/s × 15 s): czekanie p50 32.3 / p99 **63.1 s** przy obsłudze LLM
   p50 1.06 s → po zmianie czekanie p99 **0.0 s**, całość p99 1.70 s.
7. **Wariant: pula połączeń mniejsza niż semafor.** Zmienna `LLM_POLACZENIA` ustawia `max_connections`
   klienta httpx2 (0 = domyślne 1000). **Hipoteza:** semafor 64, pula 8 — gdzie będzie czekanie i czy
   zobaczysz je w `llm.queue_wait`?
   ```bash
   LLM_SLOTY=64 LLM_POLACZENIA=8 uvicorn app.main:app --port 8060
   docker compose run --rm -e WYNIK=ex06-pula8 k6 run -o experimental-prometheus-rw /scripts/otwarty.js -e RATE=20 -e CZAS=15s
   ```
   U mnie: 294 × 200 + 6 × `status 0`, całość p50 13.1 / p99 25.4 s; „LLM” (wywołanie razem z czekaniem
   w puli) p50 **8.5 s** zamiast ~1 s; `llm_inflight` 64, `llm_waiting` max 116. Dowód z drugiej strony: `max_over_time(mock_llm_generating{provider="a"}[2m])` = 8 —
   dostawca nigdy nie dostał więcej niż 8 wywołań, choć semafor wpuścił 64 (jeśli poprzedni przebieg skończył
   się < 2 min temu, zawęź okno do czasu testu, np. `[40s]` — u mnie `[2m]` złapało jeszcze 21 z kroku 6).
   Czasu czekania w puli NIE
   wyprowadzaj z różnicy spanów — po prostu go nie mierzysz.
8. Ten sam wariant z krótkim `pool timeout` zobaczysz w praktyce po ćw. 10 (klient ma tam `pool=5 s`).
   Zmierzyłem go z wyprzedzeniem: przy `LLM_FALLBACK=0` **86/300** żądań kończy się `504`
   (`APITimeoutError`, pod spodem `PoolTimeout`), a z włączonym fallbackiem **77/300** żądań po cichu
   obsłużył zapasowy dostawca `b`. Zanotuj to — wrócisz do tego w ćw. 11.
9. Uruchom aplikację normalnie (bez zmiennych) i `python check.py ex06`.

## Kryteria „done”
- [ ] Domyślna liczba slotów wynika z rachunku (komentarz w `limiter.py`), ruch 20/s nie czeka na slot.
- [ ] Umiesz pokazać nasycenie zasobu trzema seriami: `llm_inflight`, `llm_waiting`, `mock_llm_generating`.
- [ ] Rozumiesz, dlaczego przy puli połączeń 8 span `llm.queue_wait` kłamie i czym to wykryć.
- [ ] `python check.py ex06` przechodzi (20/s × 10 s: czekanie p99 < 0.5 s).

## Pytania kontrolne
1. Ruch spadł do 2/s, a Ty masz 32 sloty. Czy coś tracisz, trzymając je? A przy 320 slotach?
2. Dlaczego `pool timeout = 600 s` (domyślny w SDK) jest gorszy diagnostycznie niż `5 s`?
3. Uruchamiasz 4 procesy aplikacji po 32 sloty przed dostawcą o mocy 64. Co się stanie przy pełnym ruchu?

Odpowiedzi: `solutions/pytania_odpowiedzi.md`.

## ★ Bonus (opcjonalnie)
Dodaj `LLM_POLACZENIA` do `/diag` (sekcja `klienci`) i panel w Grafanie „wywołania w toku vs pula
połączeń”. Jaki alert ustawiłbyś, żeby złapać wariant z kroku 7 zanim zobaczą go klienci?

---
Utknąłeś? `solutions/hints/ex06_hint1.md` → `hint2` → `hint3`. Gotowe rozwiązanie:
`solutions/ex06_limiter.py` → `app/llm/limiter.py` (zawiera też ćw. 1).
