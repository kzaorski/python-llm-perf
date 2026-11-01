# Ćw. 05 — podpowiedź 1 (kierunek)

Handler `def` (bez `async`) FastAPI uruchamia w puli wątków anyio. Pula ma 40 miejsc. 41. żądanie czeka
na wolny wątek — a wątki nie liczą, tylko czekają na LLM. Objaw: druga „fala” odpowiedzi, CPU prawie zero.
Czy ten handler musi być synchroniczny?
