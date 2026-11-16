# Ex. 09 — hint 1 (direction)

Count the HTTP attempts per user request (`/diag` → `http_attempts`, or
`sum(increase(llm_http_attempts_total[2m])) / sum(increase(app_requests_total{endpoint="summary"}[2m]))`).
How many layers retry the same error? How many times the SDK, how many times the application? Are the
pauses between attempts random?
