# Exercise 5: The anyio thread pool (40) — waiting that burns no CPU

> Time: ~30 min

> Block II. Reading `04a-asyncio-loop-and-pools.md` (the section on the thread pool).

## Goal
The customer letter endpoint (`POST /claims/{n}/letter`) is a plain `def` with a synchronous LLM client.
FastAPI runs such handlers in the anyio thread pool, which has a limit of **40**. You send 60 letters at
once and find the second "wave" — 20 requests wait for a free thread although the CPU is idle and the
provider has spare capacity. You fix the handler so that it does not occupy a thread while waiting for the
LLM.

## Theory in a nutshell
- **The anyio thread pool** — FastAPI `def` handlers and `run_in_threadpool` run in worker threads with a
  single global limiter: 40 at a time. Intuition: 40 service windows; the 41st customer waits until someone
  leaves. Why: it protects the process from thousands of threads. Pitfall: a thread held while waiting for
  the network (a 2 s LLM call) is a wasted window — throughput = 40 / call time.
- **Waiting without CPU** — a resource (a thread) is busy, the processor is free. The CPU profile shows
  nothing; this is a queue, not computation. Pitfall: "the CPU is idle, so it is not the application" — a
  wrong conclusion.
- **Steps in response times** — for N > 40 the times line up in waves about one call time apart:
  40 × t, then 20 × 2t. Such multimodal distributions are the signature of a fixed pool. (→ `00-theory.md`
  "Percentiles and the tail")
- **`async def` + an async client** — while waiting for the LLM the coroutine hands the loop back and holds
  no thread. You then set the concurrency limit deliberately (the slot semaphore), not by accident (40).

## Steps
1. State after ex. 4, application on 8060.
2. **Hypothesis:** 60 letters at once, each ~2.1 s at the mock (the `x-mock-ttft-ms: 2000` header sets the
   time to first token). What will the distribution of times look like? How many requests will finish after
   ~2 s, how many later, and when?
3. A wave of 60 parallel requests (sorted times, in seconds):
   ```bash
   seq 60 | xargs -P 60 -I{} curl -s -o /dev/null -w '%{time_total}\n' -X POST \
     -H 'x-mock-ttft-ms: 2000' -H 'x-mock-total-s: 0.1' 127.0.0.1:8060/claims/{}/letter | sort -n | awk '{printf "%.2f ", $1} END {print ""}'
   ```
   In my run: 40 values of 2.12–2.21 s, then 20 values of 4.19–4.33 s. The first wave right after the
   process starts can be slower (client warm-up) — repeat the command 2–3 times.
4. See what you do NOT see: `curl -s 127.0.0.1:8060/diag | python -m json.tool` — the LLM queue is empty
   (the letter does not go through the semaphore), the event loop lag is normal (the loop is not stuck — the
   threads are). And the CPU? Run the wave from step 3 once more and, in a second terminal, during it:
   ```bash
   ps -o %cpu= -p $(lsof -tiTCP:8060 -sTCP:LISTEN)
   ```
   In my run: the process's `%cpu` was **0.4** while waiting (16 at the moment the wave returns and 60
   responses are sent at once); `/diag`: LLM queue empty, `loop_lag_max_10s_ms` 2.6. Waves after warm-up:
   2.14–2.18 s and ~4.3 s (the first one right after startup: 2.85 / 5.01 s).
5. Open **`app/templates.py`** (`TODO ex. 05`). Change the handler to `async def` and the call to the
   application's async client: `await client.complete(LLMJob(...))` from `app/llm/client.py`.
   Rendering the template is fast (microseconds of CPU) — it can stay in the loop.
6. Restart and repeat step 3. In my run: one wave, 60 × 2.14–2.28 s (p99 2.28 s; before: 2.2 / 4.35 s).
7. `python check.py ex05`

## Definition of done
- [ ] 60 parallel letters finish in a single wave (max < 1.5 × min).
- [ ] You can recognize "steps every ~40" in a distribution and point to the cause without a profile.
- [ ] `python check.py ex05` passes.

## Review questions
1. Why does the symptom start at exactly the 41st request? Where is that number?
2. Raising the anyio limit to 400 also "fixes" the test. What problem are you pushing downstream that way?
3. How does this symptom differ from ex. 4 (loop blocking)? How would you tell them apart using `/diag/ping`?

Answers: `solutions/questions_answers.md`.

## ★ Bonus (optional)
Send 60 letters and, in parallel, 20 classifications (already async after ex. 4). Do the classifications
wait for the letters? Why not? And what would happen if both the letters and the classifications were `def`?

---
Stuck? `solutions/hints/ex05_hint1.md` → `hint2` → `hint3`. The ready-made solution:
`solutions/ex05_templates.py` → `app/templates.py`.
