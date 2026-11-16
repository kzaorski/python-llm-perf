# Ex. 10 — hint 3 (pseudocode)

```python
async def with_deadline(request, request_class, fn):
    work = asyncio.ensure_future(fn())
    guard = asyncio.ensure_future(_wait_for_disconnect(request)) if request else None
    try:
        async with asyncio.timeout(DEADLINE_S[request_class]):
            await asyncio.wait({work} | ({guard} if guard else set()), return_when=FIRST_COMPLETED)
    except TimeoutError:
        work.cancel(); await suppress(work); raise DeadlineExceeded(...)
    finally:
        if guard: guard.cancel()
    if work.done(): return work.result()
    work.cancel(); await suppress(work); raise ClientDisconnected()
```
Plus in `client.py`: long calls through `messages.stream(...)` (TTFT from the first event). `python check.py ex10`.
