# Ex. 01 — hint 1 (direction)

The slot wait time is already computed: in `app/llm/limiter.py`, in `slot()`, the variable `wait` (seconds)
and the marker `t0_ns` (the moment of entering the queue). All that is missing is **showing** it in three
places: a separate span in the trace, an attribute on the request span, and a histogram in the metrics.

A guiding question: should the wait span be the parent of the `llm.call` span, or its sibling? What would the
trace show if the LLM call were "inside" the wait?
