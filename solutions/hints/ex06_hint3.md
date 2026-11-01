# Ćw. 06 — podpowiedź 3 (zmiana)

W `app/llm/limiter.py`: `SLOTY = int(os.environ.get("LLM_SLOTY", "32"))` (20/s × ~1.05 s ≈ 21, zapas na ogon).
Pula połączeń klienta (`LLM_POLACZENIA`, `app/llm/klient.py`) nie może być mniejsza niż semafor. Restart,
`python check.py ex06`.
