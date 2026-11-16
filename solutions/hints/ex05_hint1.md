# Ex. 05 — hint 1 (direction)

FastAPI runs a `def` handler (without `async`) in the anyio thread pool. The pool has 40 slots. The 41st
request waits for a free thread — and the threads are not computing, they are waiting for the LLM. Symptom:
a second "wave" of responses, CPU close to zero. Does this handler have to be synchronous?
