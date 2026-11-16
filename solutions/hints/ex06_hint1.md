# Ex. 06 — hint 1 (direction)

The request waits 30–60 s although the LLM call itself takes 1 s and the mock is almost idle. The resource
being waited for is on our side. Use Little's law to compute how many calls at once you need at 20/s and
~1 s, and compare that with the application's number of slots. Also check the second "hidden" limit: the HTTP
client's connection pool.
