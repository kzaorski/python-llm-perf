# Ćw. 16 — podpowiedź 2 (metryki)

- Odpowiedź `POST /claims/{n}/priority` niesie `rozmiar_wsadu` i `czekanie_na_wsad_ms`.
- Prometheus: `histogram_quantile(0.5|0.99, sum by (le) (rate(app_batch_size_bucket[2m])))`.
- Little: okno T przy λ próśb/s zbiera średnio λ·T zgłoszeń (30/s × 0.05 s ≈ 1.5; w burście 30 naraz — więcej).
- Kryteria checka: pojedyncza < 1.2 s, przy 30 równoległych 1 < wsad ≤ 32.
