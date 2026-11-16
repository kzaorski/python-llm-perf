# Ex. 04 — hint 1 (direction)

The `async def` handler calls the **synchronous** SDK client. For the duration of that call the event loop
stands still — the process serves nothing else (not even `/diag/ping`). Look for the async path that the
other endpoints (summaries) already use, and plug classification into it.
