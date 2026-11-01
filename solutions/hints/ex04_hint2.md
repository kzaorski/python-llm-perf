# Ćw. 04 — podpowiedź 2 (API / metryka)

- Objaw: `app_event_loop_lag_seconds` (lag pętli), czas `/diag/ping`, w Tempo żądania `/classify` ułożone
  jedno za drugim; profil wall w Pyroscope potwierdza: czas w `httpx`/`ssl` read w wątku pętli.
- Naprawa: `obsluga.wykonaj(request, Zadanie(klasa="krotkie", endpoint="classify", max_tokens=16, prompt=…,
  naglowki=obsluga.naglowki_atrapy(request)))` — przez semafor, ponowienia i asynchronicznego klienta.
