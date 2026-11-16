# Ex. 05 — hint 2 (API)

- Measuring the wave: 60 parallel `POST /claims/{n}/letter` with `x-mock-ttft-ms: 2000` — the times fall into
  two steps (~2.2 s and ~4.4 s).
- Fix: `async def` + `await client.complete(LLMJob(...))` from `app/llm/client.py` (AsyncAnthropic).
  Rendering the template takes microseconds — it can stay in the loop. (The alternative, "raise the anyio
  limiter", moves the threshold; it does not remove the mechanism.)
