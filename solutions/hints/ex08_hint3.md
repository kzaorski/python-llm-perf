# Ex. 08 — hint 3 (pseudocode)

```python
class Bucket:          # limit/min, level, time of the last refill
    def time_until(n): ...  # how many seconds until n tokens
    def take(n): ...
    def sync(limit, remaining): ...  # level = min(level, remaining)

async def pace(request_class, max_tokens):
    async with _order:                         # FIFO
        while True:
            wait_s = max(_paused_until - now(), RPM.time_until(1), OTPM.time_until(max_tokens))
            if wait_s <= 0: RPM.take(1); OTPM.take(max_tokens); return
            await asyncio.sleep(min(wait_s, 1.0))
```
`python check.py ex08` (the `limits` profile, 90 at once → 429 ≤ 1%).
