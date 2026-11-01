# Ćw. 13 — podpowiedź 2 (API / metryki)

- `app_stream_first_chunk_seconds` (wysłane klientowi) vs `llm_ttft_seconds{klasa="krotkie"}` (od dostawcy);
  `python scripts/strumien_ttft.py -n 20 -c 5` — klient, który czyta strumień. k6 `http_req_waiting` = czas do
  nagłówków, więc wady nie widzi.
- W `app/strumien.py`: `yield sse("delta", …)` od razu w pętli `async for`; `pierwszy_fragment(czasy, t0)`
  przy pierwszym; co ~20 fragmentów `await request.is_disconnected()` → koniec z `wynik = "anulowane"`.
