# Ex. 12 — hint 1 (direction)

Two separate problems: (1) short and long requests share one pool — long ones hold it for minutes
(head-of-line blocking); (2) the queue has no bottom — you accept more than you can serve, and clients
give up after minutes. Split the pools per class and say "not now" quickly: a queue length limit and a
wait budget.
