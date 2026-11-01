# Ćw. 09 — podpowiedź 1 (kierunek)

Policz próby HTTP na jedno żądanie użytkownika (`/diag` → `proby_http`, albo
`sum(increase(llm_http_attempts_total[2m])) / sum(increase(app_requests_total{endpoint="summary"}[2m]))`).
Ile warstw ponawia ten sam błąd? Ile razy SDK, ile razy aplikacja? Czy przerwy między próbami są losowe?
