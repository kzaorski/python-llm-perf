# Ćwiczenie 8: Limity dostawcy — 429, nagłówki `anthropic-ratelimit-*` i limiter po naszej stronie

> Czas: ~45 min (dwa przebiegi po 60 s; drugi opróżnia kolejkę ~1 min po końcu dopływu)

> Blok III — Dostawca: limity, ponowienia, timeouty, fallback (ćw. 8–11). Najpierw czytanka
> `08a-limity-retry-timeouty.md`.

## Cel
Przełączasz atrapę na profil `limity` (limity konta jak u prawdziwego dostawcy: żądania/min, tokeny
wejścia/min, tokeny wyjścia/min) i puszczasz ruch powyżej limitu. Liczysz 429 u dostawcy, czytasz
nagłówki limitów i dopisujesz limiter tempa, który zamienia lawinę 429 w kontrolowane czekanie po
naszej stronie. Zobaczysz też, czego limiter NIE naprawi: przepustowości.

## Teoria w pigułce
- **Limity dostawcy LLM** — kubełki żetonów uzupełniane ciągle: RPM (żądania/min), ITPM (tokeny
  wejścia/min), OTPM (tokeny wyjścia/min; dostawca rezerwuje `max_tokens` na starcie wywołania). Przekroczenie
  któregokolwiek → `429 rate_limit_error` + `retry-after`. Pułapka: przy krótkich promptach i dużym
  `max_tokens` wąskim gardłem jest OTPM, nie RPM.
- **Nagłówki** — każda odpowiedź niesie `anthropic-ratelimit-{requests,input-tokens,output-tokens}-{limit,remaining,reset}`.
  Po co: klient zna limit i stan kubełka, zanim dostanie 429. Pułapka: odpowiedź bez strumienia niesie
  nagłówki dopiero po całej generacji — nie czekaj na nie, zanim wyślesz pierwsze żądanie.
- **Limiter po stronie klienta** — własny kubełek (token bucket) zsynchronizowany z nagłówkami;
  przed wywołaniem czekasz na żeton, po 429 wstrzymujesz wszystkich do `retry-after`. Po co: 429 to
  zmarnowane połączenie i (przy ponowieniach) mnożenie ruchu. Pułapka: limiter nie zwiększa pojemności —
  nadmiar nadal czeka, tylko u nas. Bez limitu tej kolejki (ćw. 12) czekanie rośnie bez końca.
- **Dlaczego przy 4 slotach nie było 429?** Mała pula slotów sama w sobie była limiterem współbieżności.
  Po ćw. 6 (32 sloty) aplikacja potrafi wreszcie przeciążyć dostawcę — kolejność ćwiczeń nie jest przypadkowa.

## Kroki
1. Stan po ćw. 7, aplikacja na 8060 (32 sloty). Profil atrapy:
   ```bash
   curl -s -X POST 127.0.0.1:8061/admin/profile/limity
   curl -s -D - -o /dev/null -H 'x-api-key: mock-key' -H 'anthropic-version: 2023-06-01' -H 'content-type: application/json' \
     -d '{"model":"claude-haiku-5-5","max_tokens":200,"messages":[{"role":"user","content":"test"}]}' \
     127.0.0.1:8061/v1/messages | grep -i ratelimit
   ```
   ⟨E08-NAGLOWKI⟩
2. **Rachunek i hipoteza.** Streszczenie ma `max_tokens=200`. Ile streszczeń/min przepuści limit tokenów
   wyjścia? A RPM? Co się stanie przy ruchu 3/s przez 60 s (180 żądań)? Ile 429 zobaczy atrapa, ile błędów klient?
3. Ruch:
   ```bash
   docker compose run --rm -e WYNIK=ex08-przed k6 run -o experimental-prometheus-rw /scripts/otwarty.js -e RATE=3 -e CZAS=60s
   curl -s 127.0.0.1:8061/admin/stats | python -m json.tool | head -20
   ```
   ⟨E08-PRZED⟩
4. Prometheus — co widzi dostawca, a co aplikacja:
   ```
   sum by (status) (increase(mock_llm_requests_total{provider="a"}[3m]))
   sum by (status) (increase(llm_http_responses_total{dostawca="a"}[3m]))
   ```
   Klient dostał mniej błędów niż atrapa 429 — dlaczego? (Podpowiedź: kto ponawia, ćw. 9.)
5. Otwórz **`app/llm/limiter.py`**: `tempo()` i `aktualizuj_z_naglowkow()` (`TODO ćw. 08`). Dopisz:
   - dwa kubełki: żądania/min i tokeny wyjścia/min (rezerwujesz `max_tokens`), uzupełniane ciągle,
   - `aktualizuj_z_naglowkow()`: z `*-limit` i `*-remaining` ustawiasz limit i korygujesz poziom w dół;
     przy `status == 429` wstrzymujesz wszystkich do `retry-after`,
   - `tempo()`: czekasz (FIFO, `asyncio.Lock`), aż oba kubełki mają żetony i minęła pauza; dopóki nie
     znasz limitów (pierwsze odpowiedzi) — nie ograniczasz (pierwszą falę trzyma pula slotów).
6. Restart aplikacji, ponownie `curl -s -X POST 127.0.0.1:8061/admin/profile/limity` (profil ustawia też
   pełne kubełki limitów), powtórka kroku 3 z `-e WYNIK=ex08-po`. ⟨E08-PO⟩

   U mnie (harness, 3/s × 60 s): **133 × 429** u atrapy i 7 żądań zakończonych `503 limit_dostawcy`,
   p99 6.7 s → **0 × 429**, 180/180 OK, ale czekanie na slot p99 **58.2 s** — nadmiar czeka u nas.
7. Zresetuj atrapę: `curl -s -X POST 127.0.0.1:8061/admin/reset` i `python check.py ex08`
   (check sam ustawia profil `limity` i wysyła 90 żądań naraz).

## Kryteria „done”
- [ ] Przy profilu `limity` atrapa nie zwraca 429 (≤ 1%), wszystkie żądania kończą się 200.
- [ ] Umiesz policzyć z nagłówków, ile żądań danego typu przepuści limit na minutę.
- [ ] Rozumiesz, dlaczego po naprawie p99 nadal jest długie i co z tym zrobi ćw. 12.
- [ ] `python check.py ex08` przechodzi.

## Pytania kontrolne
1. Dlaczego limiter rezerwuje `max_tokens`, a nie faktyczną liczbę tokenów odpowiedzi?
2. Dwa procesy aplikacji, każdy ze swoim kubełkiem. Co się stanie i jak pomagają nagłówki `*-remaining`?
3. Po co wstrzymywać WSZYSTKICH po pierwszym 429, a nie tylko to jedno żądanie?

Odpowiedzi: `solutions/pytania_odpowiedzi.md`.

## ★ Bonus (opcjonalnie)
Dodaj trzeci kubełek: tokeny wejścia/min (ITPM), z liczbą tokenów oszacowaną z długości promptu.
Zbuduj ruch, w którym to ITPM jest wąskim gardłem (długie zgłoszenia, `max_tokens` małe).

---
Utknąłeś? `solutions/hints/ex08_hint1.md` → `hint2` → `hint3`. Gotowe rozwiązanie:
`solutions/ex08_limiter.py` → `app/llm/limiter.py` (zawiera ćw. 1 i 6).
