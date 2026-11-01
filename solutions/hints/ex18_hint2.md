# Ćw. 18 — podpowiedź 2 (gdzie patrzeć)

- Streszczenia: `max by (klasa) (llm_inflight)` vs `max(mock_llm_generating)`; czekanie na slot p50; wyniki
  `odrzucone`. Ile slotów ma aplikacja i czy dostawca jest zajęty?
- Strumień: `app_stream_first_chunk_seconds` vs `llm_ttft_seconds`; `python scripts/strumien_ttft.py -n 20 -c 5`.
- FAQ: `sum by (wynik) (increase(app_cache_total[5m]))` — ile chybień na 5 pytań przy TTL 30 s?
- Analizy: `sum by (phase) (increase(mock_llm_cancelled_total[10m]))` i `mock_llm_generating` PO końcu ruchu.
- Wykluczenia: próby HTTP / żądanie (`llm_http_attempts_total`), 429/529 u atrapy, lag pętli.
