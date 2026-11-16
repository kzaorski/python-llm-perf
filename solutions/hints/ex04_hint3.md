# Ex. 04 — hint 3 (pseudocode)

```python
@router.post("/claims/{n}/classify")
async def classify(n: int, request: Request):
    z = LLMJob(request_class="short", endpoint="classify", max_tokens=16, system=SYSTEM,
               prompt=_prompt(n), headers=pipeline.mock_headers(request))
    w = await pipeline.execute(request, z)
    return {"claim": data.claim(n)["id"], "category": _category(w.text, n)}
```
Remove `_sync_client` and the manual `record_outcome` (`pipeline.execute` does that). `python check.py ex04`.
