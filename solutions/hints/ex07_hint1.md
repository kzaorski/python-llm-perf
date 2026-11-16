# Ex. 07 — hint 1 (direction)

A gunicorn sync worker serves one request at a time. The application waits on I/O (the LLM), it does not
compute — so throughput = number of processes / call time, and every process costs tens of MB. On top of
that, the default `--timeout 30` kills the worker on a longer call. Which worker type can serve hundreds of
waiting requests in a single process?
