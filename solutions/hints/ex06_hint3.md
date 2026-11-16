# Ex. 06 — hint 3 (change)

In `app/llm/limiter.py`: `SLOTS = int(os.environ.get("LLM_SLOTS", "32"))` (20/s × ~1.05 s ≈ 21, headroom
for the tail). The client's connection pool (`LLM_CONNECTIONS`, `app/llm/client.py`) must not be smaller than
the semaphore. Restart, `python check.py ex06`.
