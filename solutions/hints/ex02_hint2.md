# Ćw. 02 — podpowiedź 2 (API)

Executor `constant-arrival-rate`: `rate` (ile iteracji), `timeUnit` (`'1s'`), `duration`, `preAllocatedVUs`,
`maxVUs`. VU w tym modelu to tylko „robotnicy” do wysyłania — potrzeba ich ≈ tempo × najdłuższy czas
odpowiedzi (Little). Sprawdzaj `dropped_iterations` w podsumowaniu (i `k6_dropped_iterations_total` w
Prometheusie) — musi być 0. Tag `model: 'otwarty'` (już jest w pliku) pozwala porównać serie w Prometheusie; `gracefulStop` > najdłuższe żądanie.
