# Ex. 16 — hint 1 (direction)

Measure the two ends: one request when nobody else is asking (how long does it wait for the window?), and 30 at once (how big are the
batches?). The window is the time you add to everyone under low traffic; the size is the limit on how many claims one call
carries. Both parameters are in `app/batch.py` and require no new code.
