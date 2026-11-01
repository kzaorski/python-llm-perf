# Ćw. 01 — podpowiedź 1 (kierunek)

Czas czekania na slot już jest policzony: w `app/llm/limiter.py`, w `slot()`, zmienna `czekanie` (sekundy)
i znacznik `t0_ns` (chwila wejścia do kolejki). Brakuje tylko jego **pokazania** w trzech miejscach:
osobny span w trace, atrybut na spanie żądania i histogram w metrykach.

Pytanie pomocnicze: czy span czekania ma być rodzicem spanu `llm.call`, czy jego rodzeństwem? Co by pokazał
trace, gdyby wywołanie LLM było „wewnątrz” czekania?
