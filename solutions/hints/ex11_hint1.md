# Ex. 11 — hint 1 (direction)

When provider `a` is silent, every request first waits for its timeout and only then goes to `b`. You need
memory: "`a` has been failing lately — do not ask it at all for a while", and every so often a single probe
request checks whether it is back. That is a circuit breaker with three states.
