# Ex. 17 — hint 3 (calculation)

Slots = λ × W. For summaries: W_claude ≈ 1.23 s (med), the tail up to ~1.8 s; at 20/s → ~25 (med) / ~36 (tail).
For a reply of 700 tokens: W ≈ 0.48 + 700/225 ≈ 3.6 s → at the same λ ~3× more slots than for summaries.
Read timeout of the short calls: a multiple of the maximum silence, not the maximum (the tail at other hours can be longer).
