# Ćw. 04 — podpowiedź 1 (kierunek)

Handler `async def` wywołuje **synchronicznego** klienta SDK. Na czas tego wywołania pętla zdarzeń stoi —
proces nie obsługuje nic innego (nawet `/diag/ping`). Szukaj ścieżki asynchronicznej, której używają już
inne endpointy (streszczenia), i podłącz do niej klasyfikację.
