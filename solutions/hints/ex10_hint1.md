# Ćw. 10 — podpowiedź 1 (kierunek)

Trzy różne rzeczy, które łatwo pomylić: **timeout SDK** (per operacja — read = bezczynność, nie całość),
**deadline** (całkowity czas, na który aplikacja się godzi) i **anulowanie** (klient zniknął → przerwij pracę
i oddaj slot). Długie wywołania (60–300 s) potrzebują strumienia: wtedy read timeout mierzy ciszę między
zdarzeniami, a nie długość generacji. I nie ponawiaj wywołań, które przekroczyły czas.
