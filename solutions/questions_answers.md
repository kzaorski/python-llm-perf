# Odpowiedzi do pytań kontrolnych (ćw. 01–18) i mini-incydentów I–IV

Liczby w odpowiedziach pochodzą z pomiarów autora (te same polecenia co w ćwiczeniach). U Ciebie będą
inne w szczegółach — ważny jest kierunek i rząd wielkości.

## Ex. 01 — the first trace
1. `start_span` without activation does not set the span as the current context, so the next span
   (`llm.call`) does not become its child. Had the wait been active (`start_as_current_span`), `llm.call` would
   hang under `llm.queue_wait`, and in the trace view the wait would "contain" the call — a false picture:
   waiting time and working time would merge into one bar.
2. 40 requests / 4 slots = 10 "rounds" of ~1 s → the last one waits ~9 s and finishes after ~10 s. That is
   Little's law in the single-wave version: wait time = (position in the queue / number of slots) × service time.
3. `Server-Timing` is read by the client (browser DevTools, k6 — the `app_wait_*` trends) with no access to the
   telemetry backend; the trace is read by the application team — with context (which provider, retries, SDK
   spans). The same breakdown seen from two sides lets the client report "I waited 3 s for a slot" and lets you
   find that trace.

## Ex. 02 — open vs closed model
1. 4 VUs = at most 4 requests in the system at once; each gets a slot right away, because the previous ones are
   released before the VU sends the next. A queue cannot form — the generator itself adjusts its rate to the
   capacity (coordinated omission).
2. k6 had no free VU at the moment an iteration was scheduled to start and skipped it — the model stopped being
   open exactly when the system slowed down. The result understates the tail just like the closed model does;
   you need to give it more `preAllocatedVUs`/`maxVUs` (≥ rate × the longest response time) and repeat.
3. When the client population really is closed and waits for the response: e.g. a few claims adjusters who click
   "next claim" only after reading the summary, or a task queue worker with a fixed concurrency (ex. 14).
   Traffic from the internet / from other systems — open.

## Ex. 03 — Little's law
1. Capacity 32 / 1.06 s ≈ 30.2/s; excess 40 − 30.2 ≈ 9.8/s × 60 s ≈ **590 waiting** after a minute (with no
   queue limit). The last of them waits ≈ 590 / 30.2 ≈ **19.5 s** (and longer with every second).
2. Slots are held only by the LLM call (W in L = λ·W is the time the resource is held). The time from k6
   includes the slot wait — had you used it, under overload the "slots needed" would keep growing
   (a feedback loop).
3. The knee will shift 3× to the left (capacity ~10/s instead of ~30/s). Three times more slots means 3× more
   parallel connections, memory for in-flight responses and — above all — concurrency at the provider, whose
   limit (capacity, ITPM/OTPM) may be lower than your slots.

## Ćw. 04 — synchroniczny klient w `async def`
1. Wąskim gardłem nie jest semafor, tylko pętla zdarzeń: blokujące wywołanie zatrzymuje cały proces, więc
   naraz trwa najwyżej jedno wywołanie niezależnie od liczby slotów.
2. Wszystkie endpointy dzielą jedną pętlę zdarzeń. Gdy stoi (blokujący odczyt z gniazda w handlerze
   klasyfikacji), żadna inna korutyna — streszczenie, `/health`, `/diag/ping` — nie dostaje czasu.
3. Proces obsługuje ~1 wywołanie/s, więc ~6–8 procesów (z zapasem na ogon). Zła naprawa: każdy proces to
   osobna pamięć, osobny klient i limity, a mechanizm (proces = 1 żądanie) zostaje — przy wywołaniach
   minutowych potrzebowałbyś setek procesów.

## Ćw. 05 — pula wątków anyio
1. Handlery `def` FastAPI wykonuje w puli wątków anyio, której domyślny limiter ma 40 miejsc
   (`anyio.to_thread.current_default_thread_limiter().total_tokens`). 41. żądanie czeka na wolny wątek.
2. Każdy wątek to pamięć stosu i przełączanie przez system; przy 400 wątkach i wywołaniach minutowych dalej
   rośnie zużycie zasobów, a limit tylko się przesuwa (przy 401 równoległych objaw wraca). Do tego wątki nie
   podlegają semaforowi/limiterowi aplikacji, jeśli wołają klienta synchronicznego bezpośrednio.
3. Ćw. 4: pętla stoi — `/diag/ping` trwa sekundy, wszystkie endpointy cierpią. Ćw. 5: pętla wolna — ping w
   milisekundach (u mnie 1.3 ms w trakcie fali), cierpi tylko endpoint `def` i tylko powyżej 40 równoległych.

## Ćw. 06 — pula slotów i połączeń
1. Przy 2/s potrzeba ~2–3 slotów; 32 to tylko liczba dopuszczalna, a nie zajęta — semafor nie kosztuje nic, gdy
   jest wolny. Przy 320 slotach tracisz ochronę: w szczycie wyślesz dostawcy więcej, niż ma mocy/limitu
   (429/529, ćw. 08–09), a kolejka przeniesie się z Twojego semafora (widoczna) do dostawcy (niewidoczna).
2. Z `pool=600` czekanie na połączenie jest ciche (nie trafia do `llm.queue_wait`), żądanie po prostu trwa
   dłużej. Z `pool=5` przeciążenie puli daje szybki, nazwany błąd (`PoolTimeout` → `APITimeoutError`) —
   widać przyczynę, a nie tylko ogon.
3. 4 × 32 = 128 równoległych przy mocy 64: połowa czeka w kolejce dostawcy albo dostaje 529 — sloty trzeba
   dzielić per proces (np. 16 na proces) albo mieć wspólny limiter (Redis, ćw. 08).

## Ćw. 07 — gunicorn
1. Workery sync były zajęte, backlog gniazda nasłuchującego się zapełnił, a jądro odrzuciło lub zerwało
   połączenia, zanim aplikacja w ogóle zobaczyła żądania (u mnie 63/450 zerwanych). Aplikacja nie mogła
   odpowiedzieć 503, bo nie miała czym przyjąć żądania.
2. Naprawiasz zabijanie workera przy długim wywołaniu (500 + `WORKER TIMEOUT`). Nadal przepustowość = liczba
   procesów / czas wywołania, a jedno 600-sekundowe wywołanie blokuje cały proces na 10 minut.
3. Nie: gniazdo dzieli jądro, a proces, który pierwszy wywoła `accept`, bierze żądanie — rozkład bywa nierówny.
   Wtedy w jednym procesie czekają żądania na slot, choć drugi ma wolne. Czekanie mierz per proces
   (`service_instance_id`) albo daj zapas slotów.

## Ćw. 08 — limity dostawcy
1. Dostawca rezerwuje OTPM według `max_tokens` w chwili przyjęcia żądania (nie zna długości odpowiedzi), więc
   limiter po naszej stronie musi liczyć tak samo — inaczej wyśle za dużo i dostanie 429.
2. Każdy proces myśli, że ma cały limit — razem wysyłają ~2× za dużo. Nagłówki `*-remaining` są wspólnym
   stanem konta u dostawcy: korekta kubełka w dół do `remaining` synchronizuje procesy (z opóźnieniem jednej
   odpowiedzi). Pełne rozwiązanie: wspólny limiter (np. w Redisie).
3. 429 dotyczy konta, nie żądania: limit jest wyczerpany dla wszystkich. Jeśli pozostałe żądania wyślą dalej,
   każde dostanie 429 (i będzie ponawiane) — rośnie ruch i opóźnienie odnowienia limitu.

## Ćw. 09 — burza ponowień
1. Nieudane żądania po naprawie kończą się szybko błędem zamiast „wygrać” trzecią czy dziewiątą próbą przy
   przeciążonym dostawcy. Mniej sukcesów o 7%, ale ruch do dostawcy spadł z 3.65 do 1.20 próby/żądanie —
   dostawca szybciej wychodzi z przeciążenia, a w realnym systemie inni klienci dostawcy też.
2. ±10% wokół tego samego opóźnienia zostawia klientów zsynchronizowanych — wracają falą prawie w tej samej
   chwili i znowu przeciążają. Pełny jitter rozkłada powroty równomiernie na całe okno.
3. Za aplikacją: zna budżet ponowień, deadline (ćw. 10) i klasę żądania, ma metryki prób. Za SDK: poprawna
   obsługa `retry-after` i idempotencji bez własnego kodu. Tu aplikacja — bo potrzebny jest budżet i brak
   ponowień timeoutów; SDK `max_retries=0`.

## Ćw. 10 — timeouty, deadline, anulowanie
1. Timeout SDK jest per operacja (connect/read/write/pool), a read to czas ciszy między bajtami. Strumień,
   który co kilka sekund przysyła token (albo `ping`), może trwać dowolnie długo — 330 s „read” nigdy nie
   wygaśnie. Deadline to limit całkowity: `asyncio.timeout()` wokół całego wywołania.
2. Read 15 s liczy się dopiero od wysłania żądania do dostawcy; wcześniej żądanie może czekać na slot
   (semafor) i w limiterze tempa. Przy 2/s i 15 s trzymania slotu L ≈ 30 przy 32 slotach — gdy zawieszone
   wywołania z wcześniejszych sekund jeszcze trzymają sloty (albo równolegle idzie inny ruch), część żądań
   czeka na slot i dostaje 504 później. W moim powtórzeniu (sam ten ruch, 32 sloty) czekania nie było — wszystkie
   504 po 15.0 s; dodatkowe sekundy pojawiają się, gdy L zbliża się do liczby slotów.
3. W strumieniu SDK zgłasza surowy `httpx2.ReadTimeout`, nie `anthropic.APITimeoutError`. Lista wyjątków
   ponawianych/klasyfikowanych musi go znać — inaczej trafi do ogólnego „błąd dostawcy” albo, co gorsza,
   zostanie ponowiony przez ogólną regułę (`except Exception`), mnożąc wielominutowe generacje.

## Ćw. 11 — fallback z wyłącznikiem
1. 529 = dostawca przeciążony, ale działa. Fallback przerzuca na `b` ruch, który `b` też może przeciążyć,
   a otwarcie wyłącznika odcina `a` w chwili, gdy zaraz wróci. Na 529 właściwa reakcja to backoff/limit
   współbieżności (ćw. 08–09), nie zmiana dostawcy.
2. Wszystkie żądania znów płaciłyby timeout `a`, jeśli `a` nadal leży, a gdy dopiero wstaje — dostałby od
   razu pełny ruch i padł ponownie (wyłącznik oscyluje). Jedna próbka to tani test.
3. `PoolTimeout` (pula < semafor) wygląda jak awaria `a` (`APITimeoutError`). Bez wyłącznika: każde żądanie
   czeka pool timeout i po cichu idzie do `b`. Z wyłącznikiem: po 5 takich „awariach” `a` zostaje odcięty na
   30 s — cały ruch na `b`, choć `a` jest zdrowy. Wniosek: najpierw usuń przyczynę (pula), a wyłącznik licz
   tylko na błędach dostawcy, nie na własnych limitach.

## Ćw. 12 — backpressure i odrzucanie
1. Po 5 minutach klient zwykle już zrezygnował — 200 trafia „do nikogo”, a slot i generacja dostawcy zostały
   zmarnowane (przebieg C: 30 porzuconych generacji). Szybkie 503 z `Retry-After` pozwala klientowi ponowić
   później, przejść do innego kanału, a systemowi obsłużyć tych, których obsłużyć zdąży.
2. Budżet ≤ cierpliwość klienta minus czas obsługi: jeśli klient (przeglądarka, proxy, inny serwis) czeka
   najwyżej 10 s, a obsługa trwa 1–2 s, czekanie > ~5–8 s i tak skończy się porzuceniem. Aplikacja nie zna
   timeoutu klienta ani tego, czy użytkownik jeszcze patrzy — te liczby bierzesz z SLO/umowy.
3. Zwiększyć pojemność (więcej mocy u dostawcy, krótsze odpowiedzi, drugi dostawca), przesunąć w czasie
   (kolejka zadań z wynikiem asynchronicznym), zdegradować (krótsza analiza). W ćw. 14 — kolejka zadań: klient
   nie trzyma połączenia, a czekanie jest jawne (wiek najstarszego zadania).

## Ćw. 13 — streaming i TTFT
1. Czekanie na slot i limiter (czas przed wywołaniem), narzut sieci/SDK do pierwszego zdarzenia, przetworzenie
   i wysłanie pierwszego fragmentu przez aplikację.
2. Porównaj `app_stream_first_chunk_seconds` (aplikacja wysłała) z pierwszym fragmentem zmierzonym u klienta
   (`scripts/strumien_ttft.py` przez proxy). Gdy aplikacja wysyła po 0.5 s, a klient dostaje po 3 s — bufor jest
   między nimi (proxy: wyłącz buforowanie, np. `X-Accel-Buffering: no`).
3. Przed: generator zbiera całość, nie sprawdza rozłączenia — slot i generacja trwają do końca (3 s), potem
   wysyłka do zamkniętego połączenia. Po: przy najbliższym sprawdzeniu `is_disconnected()` generator kończy,
   wywołanie jest anulowane, slot wraca, dostawca przerywa generację (`mock_llm_cancelled_total`).

## Ćw. 14 — kolejka zadań
1. Nie: przy 2 × 100 „szybko” oznaczało 179/200 błędów 529. 2 × 4 = 8 = moc dostawcy, więc przepustowość
   ≈ 8 / W (u mnie ~7 zadań/s) — dokładnie tyle, ile dostawca może dać. Little: L = λ·W, przy L ograniczonym
   mocą dostawcy szybszego λ nie ma; nadwyżka czeka w kolejce, gdzie jest widoczna (lag 190 → 0).
2. Pierwszy worker pobierze (prefetch) do 100 wpisów: `pending` w jego grupie prawie równe liczbie zadań, drugi
   bezczynny. Ostatnie zadanie skończy się, gdy pierwszy przerobi całą swoją pulę — czas jak dla jednego workera,
   a `lag` = 0, więc autoskalowanie po lagu nie zadziała.
3. Na wiek najstarszego nieodebranego (np. > 60 s przez 5 min — wg obietnicy dla klienta). Długość kolejki
   nie mówi nic bez tempa obsługi (1000 zadań po 10 ms to nic, 50 po 4 min to godzina); wiek mówi wprost, jak
   długo czeka ktoś, kto czeka najdłużej.

## Ćw. 15 — cache stampede
1. Zamiast 50 wywołań walczących o 32 sloty (część czekała na slot) jest jedno wywołanie, a 49 czeka tylko na
   jego wynik — nikt nie stoi w kolejce do semafora, więc p99 ≈ czas jednego wywołania.
2. Słownik `Future` żyje w pamięci jednego procesu. Drugi proces gunicorna ma własny słownik i własne chybienie,
   więc przy N procesach masz do N wywołań. Między procesami potrzebny jest wspólny punkt: blokada w Redisie.
3. Blokada wygaśnie, kolejne żądanie zdobędzie ją i zacznie liczyć drugi raz (dwa wywołania). Dlatego TTL
   blokady > deadline wywołania (rozwiązanie: 30 s = deadline krótkich), a czekający po wygaśnięciu liczą sami.

## Ćw. 16 — batching
1. Dobry, bo każde z 146 wywołań jest małe i krótkie (wsad ≤ 5), a pojedyncza prośba nie czeka 2 s na okno —
   latencja spadła z 2.78 do 0.54 s, a liczba wywołań i tak jest kilkukrotnie mniejsza niż liczba próśb. Zły
   byłby przy twardym limicie RPM (wtedy liczba wywołań jest zasobem krytycznym) albo przy dużym wspólnym
   prompcie systemowym, którego koszt chcesz dzielić na wiele zgłoszeń.
2. Wsad 100 potrzebuje naraz ~100× tokenów wejścia — przy 20% limitu dostaje 429 (albo czeka w limiterze) cały,
   wszyscy 100 klientów naraz. Wsad 5 zmieści się w resztce limitu; 429 dotyka najwyżej 5.
3. Okno ograniczone budżetem SLO (np. ≤ 50–100 ms z 1 s) i rozmiar ograniczony z góry; przy małym ruchu wysyłaj
   natychmiast (okno adaptacyjne — bonus), przy dużym zbieraj do limitu rozmiaru. Sprawdź oba końce pomiarem.

## Ćw. 17 — atrapa vs Claude
1. Test pod obciążeniem na prawdziwym API kosztuje (każde żądanie płatne), zależy od limitów konta i wpływa na
   innych użytkowników tego konta; nie da się go powtarzalnie wywołać (429, 529 nie na zawołanie). Sekwencyjny
   pomiar daje W i jego rozkład — to wejście do modelu pojemności; zachowanie pod obciążeniem ćwiczysz na atrapie.
2. Read timeout ma wykrywać awarię, nie ogon: wielokrotność najdłuższej obserwowanej ciszy (np. 5–10× → 5–15 s
   dla krótkich, jak w ćw. 10). 1.2 s ucinałby zwykły ogon w gorszej godzinie i zamieniał go w błędy.
3. W ≈ TTFT + 700 / tempo: przy 225 tok/s ~3.6 s, przy 250 ~3.3 s, przy 301 ~2.8 s. Sloty = λ·W — różnica tempa
   o ±20% to ±20% slotów przy tym samym ruchu.

## Ćw. 18 — finał
1. Zobacz `solutions/ex18_odpowiedzi.md`: `llm_inflight{klasa="krotkie"}` przyklejone do 4 przy niedociążonym
   dostawcy (`mock_llm_generating` z krótkich ≈ 4) = za mało slotów; poprawnie działający limit kolejki daje 503
   przy slotach pracujących pełną mocą dostawcy. Pokaż zespołowi `llm_inflight` obok `mock_llm_generating`.
2. `http_req_waiting` to czas do nagłówków odpowiedzi, a `StreamingResponse` wysyła je od razu — bufor jest
   za nagłówkami. Trzeba mierzyć pierwszy fragment treści.
3. Płaci właściciel konta u dostawcy (tokeny wygenerowane „do nikogo”) i inni klienci (sloty dostawcy zajęte).
   Liczba: `mock_llm_cancelled_total` = 0 przy porzuconych żądaniach k6 i `mock_llm_generating` > 0 jeszcze
   ~2 min po końcu ruchu (u mnie drain 125 s vs 32 s po naprawie).

---

## Mini-incydenty

### Mini-I (after Block I) — "the report says OK, customers say otherwise"
- **Symptom:** k6 closed, 4 VUs: p99 1.61 s, wait 0; open traffic 4/s: p99 2.58 s, wait p99 1.46 s.
- **Evidence:** `max(llm_inflight{request_class="short"})` = 4, `llm_waiting` > 0, `llm_queue_wait_seconds` grows, and
  `mock_llm_generating` ≤ 4 (the provider is underloaded). `check.py ex06`: wait p50 21.3 s / p99 42.7 s with
  LLM 1.07 s.
- **Cause:** 4 slots — capacity ~3.8/s. The closed model adjusted itself to the capacity (coordinated omission).
- **Fix:** slots from Little's law (4/s × 1.05 s ≈ 4.2 → 8 with headroom; for 20/s → 32) + reports from the open model.

### Mini-II (po bloku II) — „pisma raz 2 s, raz 4 s”
- **Objaw:** 60 równoczesnych pism: dwie grupy czasów (~2.3 s i ~4.4 s), nic pomiędzy.
- **Ślad:** `/diag/ping` w trakcie 1.3 ms (pętla wolna), `/diag` → `kolejka` pusta (to nie semafor LLM), CPU
  procesu bliskie 0; 40 odpowiedzi w pierwszej fali.
- **Przyczyna:** endpoint pism to handler `def` → pula wątków anyio (40); 20 żądań czeka na wolny wątek.
- **Naprawa:** `async def` + asynchroniczny klient (ćw. 05); `check.py ex05` PASS.

### Mini-III (po bloku III) — „dostawca: przeciążacie nas”
- **Objaw:** dostawca widzi ~3× więcej żądań niż użytkowników, falami; część odpowiedzi 502 (u mnie 24/201).
- **Ślad:** `/diag` → 625 prób HTTP na 201 żądań (×3.11); u atrapy 448 × 529 przy 177 × 200; `/diag` →
  `klienci.krotkie.max_retries` = 2 (SDK ponawia) plus ponowienia aplikacji bez jittera (wyrównane fale);
  `check.py ex09`: ×2.40.
- **Przyczyna:** dwie warstwy ponowień (SDK × aplikacja) bez budżetu i jittera przy przeciążonym dostawcy.
- **Naprawa:** jedna warstwa (SDK `max_retries=0`), pełny jitter, `retry-after`, budżet 20% (ćw. 09);
  `check.py ex09` PASS (u mnie ×1.20).

### Mini-IV (po bloku IV) — „streszczenia wolne, kiedy działa dział analiz”
- **Objaw:** gdy w tle trwa 40 analiz po 60 s, streszczenie dostaje 503 po ~5 s (u mnie: 503 po 5.0 s).
- **Ślad:** `/diag` → `kolejka.dlugie.w_toku` = 32 (wszystkie sloty), `krotkie.w_toku` = 0; `llm_inflight`
  per klasa — długie zajmują całą pulę; limit kolejki i budżet czekania działają (stąd szybkie 503 zamiast minut).
- **Przyczyna:** jedna wspólna pula slotów dla krótkich i długich (head-of-line blocking).
- **Naprawa:** osobne pule per klasa (32 / 16, ćw. 12); `check.py ex12` PASS (krótkie czekanie p99 0 ms).
