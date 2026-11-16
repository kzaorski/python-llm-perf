# Ex. 03 — hint 3 (calculation)

1. Read W (the p50 of `llm_call_duration_seconds`) and the target λ (e.g. 20/s).
2. The slots you need: L = λ·W (+ headroom for the tail: compute from the p90/p99 of W, not the average).
3. Verify with a ramp: below the knee the wait p90 ≈ 0, above it it grows with every step.
For the check, a `results/ex03-ramp.json` with ≥ 200 requests is enough (`python check.py ex03`).
