# Pomysły na rozszerzenia kursu

Mapa umiejętności kursu jako roadmapa — co jeszcze można dodać jako wadę do diagnozy albo ćwiczenie.

| Pomysł | Umiejętność diagnostyczna | Wada / sygnał |
|---|---|---|
| Wspólny limiter tempa w Redisie dla wielu procesów | limity dostawcy przy skalowaniu poziomym | 2 procesy × własny kubełek → 2× za dużo, 429 mimo limitera (ćw. 08, pytanie 2) |
| Proxy (nginx) z buforowaniem odpowiedzi przed aplikacją | buforowanie strumienia poza aplikacją | `app_stream_first_chunk_seconds` OK, TTFT u klienta ≈ całość (ćw. 13, pytanie 2) |
| Hedging (wysłanie drugiej kopii po p95) | ogon latencji vs koszt | ruch do dostawcy +5–10%, p99 w dół; bez budżetu — amplifikacja jak w ćw. 09 |
| Priorytety w jednej puli (pożyczanie slotów) | bulkhead vs wykorzystanie | bonus ćw. 12 jako pełne ćwiczenie z pomiarem drainu |
| Długie analizy przez kolejkę zadań z deadline'em zadania | kolejka zadań + wiek najstarszego jako SLO | bonus ćw. 14: wiek najstarszego rośnie bez limitu zamiast 503 |
| Autoskalowanie workerów po `kolejka_wiek_najstarszego_s` | sterowanie pojemnością | skalowanie po `lag` nie działa przy dużym prefetchu (W15) |
| Prompt caching dostawcy | koszt i TTFT przy powtarzalnym prefiksie | TTFT i tokeny wejścia przy wspólnym prompcie systemowym (wymaga prawdziwego API) |
| Wyciek slotu przy wyjątku w strumieniu | zwalnianie zasobów w ścieżkach błędu | `llm_inflight` rośnie po każdym zerwanym strumieniu i nie wraca |
| Alerty SLO (burn rate) na odrzuceniach i wieku kolejki | operacyjne wykrywanie przeciążenia | bonus finału jako osobne ćwiczenie |
