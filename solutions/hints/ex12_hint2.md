# Ex. 12 — hint 2 (API / metrics)

- `app/llm/limiter.py`: a dictionary of semaphores `{"short": Semaphore(SLOTS), "long": Semaphore(SLOTS_LONG)}`,
  `SLOTS_LONG = int(os.environ.get("LLM_SLOTS_LONG", "16"))`; the sum ≤ the provider's capacity.
- `app/overload.py`: `admit(request_class)` → `raise Rejected("queue_full", retry_after=…)` when
  `MAX_WAITING[request_class]` are already waiting (64/8); `max_wait(request_class)` → 5 s / 20 s (the limiter
  raises `Rejected` once it is exceeded).
- Watch: `max by (request_class) (llm_waiting)`, `max by (request_class) (llm_oldest_waiting_age_seconds)`,
  `sum by (request_class, outcome) (increase(app_requests_total[5m]))`; after a run `results/*-run.json`.
