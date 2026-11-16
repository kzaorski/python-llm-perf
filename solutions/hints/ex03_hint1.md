# Ex. 03 — hint 1 (direction)

Little's law: L = λ·W. L — on average how many requests are "inside" (here: busy slots), λ — throughput,
W — service time. When L reaches the number of slots, λ stops growing, and the excess arrivals land in the
queue — that is the knee of the curve. Look for the moment when `llm_inflight` sticks to its maximum and
waiting starts to grow.
