# Ćwiczenie 9: Burza ponowień — jedna prośba, dziewięć prób

> Czas: ~40 min (dwa przebiegi po 20 s + analiza)

> Blok III. Czytanka `08a-limity-retry-timeouty.md` (ponowienia, backoff, jitter, budżet ponowień).

## Cel
Dostawca jest przeciążony (profil `przeciazenie`: moc 8 generacji, kolejka 8, nadmiar dostaje
`529 overloaded`). Aplikacja ponawia błędy szybko i bez jittera — NAD ponowieniami, które już robi SDK.
Mierzysz amplifikację: ile prób HTTP przypada na jedno żądanie klienta i czy ponowienia w ogóle coś
ratują. Zostawiasz jedną warstwę ponowień z backoffem, jitterem i budżetem.

## Teoria w pigułce
- **Amplifikacja ponowień** — warstwy mnożą się: SDK `max_retries=2` (3 próby) × aplikacja 3 próby
  = do 9 prób HTTP na jedną prośbę. Przy przeciążeniu każda próba dokłada ruchu dokładnie tam, gdzie go
  za dużo. Pułapka: każda warstwa z osobna wygląda rozsądnie.
- **Backoff wykładniczy z pełnym jitterem** — przerwa = losowa z [0, min(limit, baza · 2^próba)].
  Wykładniczy daje dostawcy czas, jitter rozbija synchronizację: klienci, którzy dostali błąd w tej samej
  chwili, nie wracają tą samą falą. Stała przerwa 100 ms = wszyscy wracają razem.
- **`retry-after`** — 429 i 529 mówią, kiedy wrócić. Honoruj to przed własnym backoffem.
- **Budżet ponowień** — ponowienia ≤ ułamek (np. 20%) żądań w ostatnim oknie. Przy masowej awarii
  ponawiasz mało, zamiast mnożyć ruch ×3. Pułapka: bez budżetu ponowienia są „darmowe” tylko przy
  rzadkich błędach.
- **Nie ponawiaj timeoutów (na tym poziomie)** — dostawca, który nie odpowiedział w czasie, zwykle
  dalej pracuje nad poprzednią próbą; powtórka podwaja jego obciążenie i Twoje czekanie (ćw. 10).

## Kroki
1. Stan po ćw. 8, aplikacja na 8060. Profil atrapy:
   ```bash
   curl -s -X POST 127.0.0.1:8061/admin/profile/przeciazenie
   ```
2. Zajrzyj do konfiguracji klientów: `curl -s 127.0.0.1:8060/diag | python -m json.tool` → `klienci`:
   `max_retries` klienta krótkich. Ile prób maksymalnie wykona jedna prośba, licząc też
   `app/llm/ponowienia.py` (3 próby co 100 ms)?
3. **Hipoteza:** ruch 10/s przez 20 s (200 żądań), dostawca przyjmuje 8 + 8 w kolejce. Ile prób HTTP na
   jedno żądanie? Ile 529? Czy ponowienia uratują większość żądań?
   ```bash
   docker compose run --rm -e WYNIK=ex09-przed k6 run -o experimental-prometheus-rw /scripts/otwarty.js -e RATE=10 -e CZAS=20s
   ```
4. Policz amplifikację (aplikacja liczy KAŻDĄ próbę HTTP, także te wewnątrz SDK):
   ```bash
   curl -s 127.0.0.1:8060/diag | python -c "import json,sys; d=json.load(sys.stdin); p=sum(x['n'] for x in d['proby_http']); z=sum(x['n'] for x in d['wyniki'] if x['endpoint']=='summary'); print('próby HTTP', p, 'żądania', z, 'na żądanie', round(p/max(z,1),2))"
   ```
   i w Prometheusie (te same liczby w czasie):
   ```
   sum(increase(llm_http_attempts_total[2m])) / sum(increase(app_requests_total{endpoint="summary"}[2m]))
   sum by (status) (increase(llm_http_responses_total[2m]))
   ```
   ⟨E09-PRZED⟩ (licznik `/diag` jest od startu procesu — mierz na świeżo uruchomionej aplikacji).
5. Napraw dwie rzeczy:
   - **`app/llm/klient.py`**: klient krótkich bez ponowień SDK (`max_retries=0`) — jedna warstwa ponowień;
   - **`app/llm/ponowienia.py`**: backoff wykładniczy z pełnym jitterem (baza 0.5 s, limit 8 s),
     pierwszeństwo `retry-after`, budżet ponowień 20% w oknie 10 s, bez ponawiania timeoutów
     (`anthropic.APITimeoutError`, `httpx2.TimeoutException`). Pamiętaj: 529 to `anthropic.OverloadedError`
     — nie jest podklasą `InternalServerError`.
6. Restart aplikacji, `curl -s -X POST 127.0.0.1:8061/admin/profile/przeciazenie`, powtórka kroków 3–4
   z `-e WYNIK=ex09-po`. ⟨E09-PO⟩

   U mnie (harness, 10/s × 20 s): **3.65 próby HTTP / żądanie** (730 prób, 567 × 529), 163 OK, p99 6.4 s →
   **1.20** (240 prób, 88 × 529), 152 OK, p99 3.6 s. Sukcesów prawie tyle samo — ponowienia bez backoffu
   niczego nie ratowały, tylko trzykrotnie obciążały dostawcę.
7. `curl -s -X POST 127.0.0.1:8061/admin/reset` i `python check.py ex09`.

## Kryteria „done”
- [ ] Przy profilu `przeciazenie` na jedno żądanie przypada ≤ 1.5 próby HTTP.
- [ ] Jedna warstwa ponowień (SDK `max_retries=0` dla krótkich), z jitterem, `retry-after` i budżetem.
- [ ] Umiesz policzyć amplifikację z `/diag` i z Prometheusa.
- [ ] `python check.py ex09` przechodzi.

## Pytania kontrolne
1. Po naprawie sukcesów jest MNIEJ (152 vs 163). Dlaczego to nie jest regresja?
2. Dlaczego pełny jitter (losowo od 0) jest lepszy od „backoff ± 10%”?
3. Gdzie powinna żyć jedyna warstwa ponowień — w SDK czy w aplikacji? Co przemawia za każdą opcją tutaj?

Odpowiedzi: `solutions/pytania_odpowiedzi.md`.

## ★ Bonus (opcjonalnie)
Profil `niestabilny` (losowe 529/500 i błędy w połowie strumienia) przy ruchu 2/s: czy budżet ponowień
blokuje sensowne ponowienia przy małym ruchu? Jak dobrać minimalny budżet (`max(1, 20%)` w rozwiązaniu)?

---
Utknąłeś? `solutions/hints/ex09_hint1.md` → `hint2` → `hint3`. Gotowe rozwiązanie:
`solutions/ex09_ponowienia.py` → `app/llm/ponowienia.py` i `solutions/ex09_klient.py` → `app/llm/klient.py`.
