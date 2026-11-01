# Ćw. 03 — podpowiedź 3 (obliczenie)

1. Odczytaj W (p50 `llm_call_duration_seconds`) i λ docelowe (np. 20/s).
2. Potrzebne sloty L = λ·W (+ zapas na ogon: licz z p90/p99 W, nie ze średniej).
3. Sprawdź rampą: przy λ poniżej kolana czekanie p90 ≈ 0, powyżej rośnie z każdym krokiem.
Do checka wystarczy `wyniki/ex03-rampa.json` z ≥ 200 żądaniami (`python check.py ex03`).
