# Ex. 02 — hint 1 (direction)

Closed model: the number of "users" (VUs) is fixed, and each waits for the response before sending the next
request — the rate depends on the system. Open model: requests arrive at a given rate regardless of whether
the previous ones have finished. In k6 this is a difference in the scenario's **executor**, not in the code of
the `default` function.
