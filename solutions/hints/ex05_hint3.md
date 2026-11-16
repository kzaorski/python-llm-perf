# Ex. 05 — hint 3 (pseudocode)

```python
@router.post("/claims/{n}/letter")
async def letter(n: int, request: Request):
    z = data.claim(n)
    w = await client.complete(LLMJob(request_class="short", endpoint="letter", max_tokens=300,
                                     prompt=_prompt(z), headers=pipeline.mock_headers(request)))
    return {... as before, with w.text ...}
```
`python check.py ex05` — 60 responses in a single wave.
