# Ćw. 05 — podpowiedź 2 (API)

- Pomiar fali: 60 równoległych `POST /claims/{n}/letter` z `x-mock-ttft-ms: 2000` — czasy układają się w
  dwa schodki (~2.2 s i ~4.4 s).
- Naprawa: `async def` + `await klient.zapytaj(Zadanie(...))` z `app/llm/klient.py` (AsyncAnthropic).
  Renderowanie szablonu trwa mikrosekundy — może zostać w pętli. (Alternatywa „podnieś limiter anyio”
  przesuwa próg, nie usuwa mechanizmu.)
