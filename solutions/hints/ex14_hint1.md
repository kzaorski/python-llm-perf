# Ex. 14 — hint 1 (direction)

Two things: (1) the metric — `XLEN` counts all entries in the stream, including processed ones; the queue length
is described by the **consumer group** (what is undelivered, what is in progress); (2) concurrency — the worker accepts 2 × 100
tasks at a time, while the provider has a capacity of 8. Why does the queue look empty with such a worker?
