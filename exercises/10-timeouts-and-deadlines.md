# Exercise 10: Timeouts, deadlines and cancellation — calls that last minutes

> Time: ~80 min, including ~15 min of multi-minute tests (each scenario takes 1–5 min, before and after the fix)

> Block III. Reading `08a-limits-retries-timeouts.md` (per-operation timeout vs total deadline,
> slow first token, cancellation); `00-theory.md` "Multi-minute calls".

## Goal
The claim file analysis (`POST /claims/{n}/analysis`, the "long" class) takes 60–300 s at the provider.
You check three things that quietly break with calls like these: (1) a timeout shorter than the expected
response time plus SDK retries, (2) no cancellation when the client gives up, (3) no sensible timeout for
short requests when the provider hangs. You run every scenario for real — several minutes of wall-clock
time — and watch what happens in the meantime to the slots, the queue and the provider.

## Theory in a nutshell
- **An SDK timeout is a set of PER-OPERATION limits, not a total time.** `timeout=60` in the anthropic/httpx2
  client means: connect ≤ 60 s, EACH read ≤ 60 s, and so on. A read resets the clock — a 150 s stream with
  `read=30 s` completes correctly. Pitfall: "a 60 s timeout" does not guarantee that the request finishes
  in 60 s.
- **Without a stream, read = the time to the WHOLE response.** A non-streaming call stays silent until the
  provider finishes generating. A 120 s analysis with `read=60` always ends in a timeout — and an SDK with
  `max_retries=2` retries it twice: the user waits ~3 × 60 s for an error, and the provider starts 3
  generations (cost ×3).
- **Stream + ping** — with a stream the read timeout becomes an IDLE limit between events (tokens, or
  `ping`s that the provider sends during silence every ~15 s). Pitfall: a timeout IN THE MIDDLE of a stream
  is a raw `httpx2.ReadTimeout`, not `anthropic.APITimeoutError` — `except APITimeoutError` will not catch it.
- **The total deadline** — `asyncio.timeout(...)` around all the work in the application; after it expires
  the task is cancelled, the connection to the provider is closed, and the provider aborts the generation.
  It is the only place where you set "at most X seconds".
- **Cancellation on disconnect** — when the client (a browser, a proxy, k6) gives up, work done for it is
  pure waste: a semaphore slot, a slot at the provider, tokens. You have to detect it
  (`request.is_disconnected()`) and cancel the call. Pitfall: the `@app.middleware("http")` middleware
  (BaseHTTPMiddleware) in Starlette breaks disconnect detection — the course application has its middleware
  written as pure ASGI.
- **The timeout chain** — outer client > application deadline > SDK timeouts. k6 defaults to 60 s per
  request (the course scripts set more), gunicorn `-k sync` to 30 s (ex. 7). A deliberately short timeout
  should give a clear symptom (a 504 with a cause), not accidentally invalidate the test.

## Steps
**Preparation.** In this exercise, run the application with the fallback provider turned off — otherwise a
hang at `a` is duplicated at `b` and the numbers are unreadable (fallback is ex. 11):
```bash
LLM_FALLBACK=0 uvicorn app.main:app --port 8060
```
Watch during every test (Grafana → Prometheus, 5 s refresh):
```
max_over_time(mock_llm_generating{provider="a"}[10m])
sum by (phase) (increase(mock_llm_cancelled_total[10m]))
max_over_time(mock_llm_oldest_inflight_seconds[10m])
```
or in the terminal (Ctrl+C stops it):
```bash
while true; do curl -s 127.0.0.1:8061/admin/stats | python -c "import json,sys; a=json.load(sys.stdin)['a']; print(a['generating'], a['waiting'], a['oldest_inflight_s'], a['responses'])"; sleep 2; done
```

### A. An analysis longer than the timeout (F17) — ~3 min before, ~2 min after
1. Look at `curl -s 127.0.0.1:8060/diag | python -m json.tool` → `clients.long`: `max_retries` and `timeout`.
2. The provider: 90 s of silence before the first token, then 30 s of generation; during the silence it
   sends a `ping` every 15 s:
   ```bash
   curl -s -X PATCH '127.0.0.1:8061/admin/config?provider=a' -H 'content-type: application/json' \
     -d '{"early_start": true, "ping_interval_s": 15}'
   ```
3. **Hypothesis:** 4 analyses at once. When and with what status will each one end? How many generations
   will the provider start?
   ```bash
   python scripts/measure.py ex10-long -- run /scripts/long.js -e N=4 -e TTFT_MS=90000 -e TOTAL_S=30
   ```
   `scripts/measure.py` runs k6 and samples `/diag` and the mock every 2 s; at the end it prints the growth
   of the mock's responses (`cancelled_*` = abandoned generations). In my run: **4 × 504 after
   181.6–191.6 s** (3 × the 60 s timeout — the SDK retries), **10 abandoned generations** at the mock.

### B. The client gives up (F16) — ~3 min before, ~30 s after
4. **Hypothesis:** 6 analyses with 150 s of generation each, but the client (k6) gives up after 20 s. What
   will happen to the generations at the provider after the disconnect? When will the slots be freed?
   ```bash
   python scripts/measure.py ex10-disconnect -- run /scripts/long.js -e N=6 -e TOTAL_S=150 -e TTFT_MS=2000 -e K6_TIMEOUT=20s
   ```
   During the run, watch the mock's `generating`. In my run: the mock keeps generating with nobody waiting
   for the result — the provider-side slots are free only **172.9 s** after the disconnect; **18 abandoned
   generations** (every analysis 3× — after the 60 s timeout the SDK retries, although the client is long
   gone).

### C. A hung provider, short requests (F6) — ~4.5 min before, ~1 min after
5. **Hypothesis:** the provider is silent for 120 s on every summary (the SDK's default read = 600 s).
   Traffic of 2/s for 30 s. How many slots will the hung calls occupy? When will the last response arrive?
   ```bash
   for i in $(seq 60); do curl -s -o /dev/null -w '%{http_code} %{time_total}\n' -X POST -H 'x-mock-ttft-ms: 120000' 127.0.0.1:8060/claims/$i/summary & sleep 0.5; done > f6.txt
   curl -s 127.0.0.1:8060/diag | python -m json.tool | head -12      # after ~30 s: slots, queue
   wait; sort -k2 -n f6.txt | tail -3
   ```
   In my run (exactly these commands): after ~30 s `/diag` → `queue.short`: **32 in flight, 28 waiting**,
   the oldest 23.5 s; 60 × 200 after 120.3–220.8 s (p50 120.8 s), the last one **258 s** after the loop
   started; mock: 32 generations at once, `mock_llm_cancelled_total` with no increase.

### The fix
6. **`app/llm/client.py`** — timeouts from the SLO, not "just in case":
   - short: `anthropic.Timeout(connect=3, read=15, write=10, pool=5)`, `max_retries=0` (from ex. 9);
   - long: a call **with a stream** (`messages.stream`, you collect the text and measure TTFT), `read=60`
     (idle — a ping every 15 s resets it), `max_retries=0` — repeating a 4-minute generation is a double
     cost; the application decides about retrying.
7. **`app/llm/call.py`** (`TODO ex. 10`) — `with_deadline()`: a deadline per class (`asyncio.timeout`, short
   30 s, long 330 s → `errors.DeadlineExceeded`) and a disconnect guard (every 0.5 s
   `request.is_disconnected()` → cancel the work → `errors.ClientDisconnected`). `request` can be `None`
   (a queue worker, batches).
8. Restart (`LLM_FALLBACK=0`) and repeat A, B, C (before A, run the `PATCH … early_start/ping` again).
   In my run, repeating C with exactly the command from step 5: **60 × 504 after 15.0–15.1 s**, the last one
   54 s after the loop started (30 s of sending + 15 s + curl overhead); mock: **59 × `cancelled_generating`**
   (the 60th aborted a moment later); `/diag` → `clients`: short `max_retries` 0, read 15 s; long
   `max_retries` 0, read 60 s. Repeating A: **4 × 200 after 122.2 s**, mock 4 × 200, 0 abandoned. Repeating
   B: k6 gives up after 20.0 s, and the mock's `generating` drops from 6 to **0** in the sample 2 s later
   (`measure.py` samples every ~2 s); **6 × `cancelled_generating`**.

   In my run:

   | Scenario | Before | After |
   |---|---|---|
   | A: 4 analyses, 90 s of silence + 30 s | 4 × 504 after 181.6–191.6 s, 10 abandoned generations | **4 × 200 after 122.0 s**, 0 abandoned |
   | B: 6 × 150 s, the client leaves after 20 s | provider-side slots free after 172.9 s, 18 abandoned | free after **0.7 s**, 6 cancelled (`cancelled_generating`) |
   | C: 120 s of silence, 2/s × 30 s | 60 × 200 only after 120–235 s; 32/32 slots busy, 28 waiting; the last one after 254 s | 60 × **504** `provider_timeout` after 15–25 s, the last one after 44.5 s |

9. Reset the mock (`curl -s -X POST 127.0.0.1:8061/admin/reset`), leave the application with
   `LLM_FALLBACK=0` and run `python check.py ex10` (a short hang → 504 < 36 s; a disconnect → the
   generation aborted within 4 s; `max_retries=0` for long).

## Definition of done
- [ ] An analysis with 90 s of silence + 30 s ends with a 200, with no abandoned generations.
- [ ] A client disconnect frees the provider-side slot within seconds (`cancelled_generating` grows).
- [ ] A hung provider gives short requests a fast 504 with a cause, instead of holding slots for minutes.
- [ ] You can draw the chain: k6 timeout > application deadline > SDK read timeout (and why in that order).
- [ ] `python check.py ex10` passes.

## Review questions
1. You set `timeout=330` on the long client. Why is this not a 330 s deadline?
2. In the table's measurement (scenario C after the fix) responses arrived after 15–25 s, although the read
   timeout is 15 s (in my repeat with the command from step 5 — exactly 15.0 s). Where can the extra
   seconds come from, and what determines whether they appear?
3. Why does the timeout exception in the middle of a stream have to be caught separately, and how does it
   affect the retries from ex. 9?

Answers: `solutions/questions_answers.md`.

## ★ Bonus (optional)
The `pauses` profile (`curl -X POST 127.0.0.1:8061/admin/profile/pauses`): a 20 s pause in the middle of
the stream. At what `read` does the call survive the pause without pings? What would happen with `read=15`?

---
Stuck? `solutions/hints/ex10_hint1.md` → `hint2` → `hint3`. A ready solution:
`solutions/ex10_client.py` → `app/llm/client.py` (includes ex. 9) and `solutions/ex10_call.py` → `app/llm/call.py`.
