# solutions/ — cumulative solutions

Each `exNN_<module>.*` file is the **full** version of a module after exercise NN (it also contains the earlier
changes to that module). Copying it unblocks you at that stage — it is the last rung of the ladder, after the
hints in `solutions/hints/`.

```bash
cp solutions/ex06_limiter.py app/llm/limiter.py      # the module's state after ex. 06 (includes ex. 01)
```

| File | Copy to | Ex. | Flaw |
|---|---|---|---|
| `ex01_limiter.py` | `app/llm/limiter.py` | 01 | (TODO: measuring the slot wait) |
| `ex02_open_model.js` | `k6/open_model.js` | 02 | F14 the closed model understates the tail |
| `ex04_classification.py` | `app/classification.py` | 04 | F1 synchronous client in `async def` |
| `ex05_templates.py` | `app/templates.py` | 05 | F2 anyio thread pool (40) |
| `ex06_limiter.py` | `app/llm/limiter.py` | 06 (+01) | F3 too few slots |
| `ex07_gunicorn.py` | `gunicorn.conf.py` | 07 | F13 sync workers / 2×CPU+1 |
| `ex08_limiter.py` | `app/llm/limiter.py` | 08 (+01, 06) | F4 no rate limiter → 429 |
| `ex09_client.py`, `ex09_retries.py` | `app/llm/client.py`, `app/llm/retries.py` | 09 | F5 SDK × application retries |
| `ex10_client.py`, `ex10_call.py` | `app/llm/client.py`, `app/llm/call.py` | 10 (+09) | F6, F16, F17 timeouts / deadline / cancellation |
| `ex11_fallback.py` | `app/llm/fallback.py` | 11 | F12 fallback without a circuit breaker |
| `ex12_limiter.py`, `ex12_overload.py` | `app/llm/limiter.py`, `app/overload.py` | 12 (+01, 06, 08) | F7, F8, F18 |
| `ex13_stream.py` | `app/stream.py` | 13 | F9 buffered stream |
| `ex14_tasks.py`, `ex14_queue_metrics.py` | `app/tasks.py`, `app/queue_metrics.py` | 14 | F15 worker concurrency/prefetch |
| `ex15_cache.py` | `app/cache.py` | 15 | F10 cache stampede |
| `ex16_batch.py` | `app/batch.py` | 16 | F11 batch window and size |

Ex. 03 (Little's law, `k6/ramp.js`) and 17 (mock vs Claude, `scripts/compare_with_claude.py`) do not change the
application code. `app/main.py` is not changed in any exercise, so there is no `*_fragments` file.

## The state "after exercise NN" without copying

`scripts/overlay.py --after NN` assembles a copy of the application in `.run/after-NN/` (your `app/` stays
untouched):

```bash
python scripts/overlay.py --after 12
uvicorn --app-dir .run/after-12 app.main:app --port 8060
```

`./smoke.sh` (the `check.py --all` regression on the solutions) and `./incident.sh` (the final) are built on it.

## Stuck? The rescue order

1. `hints/exNN_hint1.md` — direction (no code),
2. `hints/exNN_hint2.md` — which API / metric / query,
3. `hints/exNN_hint3.md` — pseudocode,
4. only then: copy the ready-made module (the table above) or run the state "after exercise NN" (`overlay.py`).

Hints exist for all 18 exercises (also 03 and 17, which do not change code, and for the final, 18).

## Other files

- `questions_answers.md` — the key to the review questions of ex. 01–18 and to mini-incidents I–IV; look at it
  AFTER you have tried to answer yourself.
- `ex18_answers.md` — the key to the final (symptom → evidence → cause → fix for every defect, interactions,
  exclusions) + the self-assessment rubric. Open it only AFTER you have written your own report.
- `todo.md` — ideas for extending the course (more flaws and exercises).
