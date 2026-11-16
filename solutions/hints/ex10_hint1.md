# Ex. 10 — hint 1 (direction)

Three different things that are easy to confuse: the **SDK timeout** (per operation — read = idle time, not
the whole), the **deadline** (the total time the application agrees to) and **cancellation** (the client
disappeared → abort the work and give the slot back). Long calls (60–300 s) need a stream: then the read
timeout measures the silence between events, not the length of the generation. And do not retry calls that
exceeded their time.
