# Ex. 14 — hint 2 (Redis / taskiq API)

- `await r.xinfo_groups(STREAM)` → the dictionary of the group `GROUP`: `lag`, `pending`, `last-delivered-id`.
- The oldest undelivered: `await r.xrange(STREAM, min="(" + last_delivered_id, max="+", count=1)`;
  age = now − (the ID in ms, the part before `-`).
- Optionally the oldest in progress: `await r.xpending(STREAM, GROUP)` → `min`.
- Worker: `--workers 2 --max-async-tasks 4` (2 × 4 = 8 = the provider's capacity); the prefetch (the broker's `xread_count`) =
  `TASKS_MAX_ASYNC`, not 100.
