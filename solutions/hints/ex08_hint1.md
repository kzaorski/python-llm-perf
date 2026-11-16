# Ex. 08 — hint 1 (direction)

The provider tells you how much you have left: the `anthropic-ratelimit-*-remaining` / `-limit` / `-reset`
headers in every response and `retry-after` on a 429. Instead of collecting 429s and retrying, wait
**on your side**, before you send a call that has no chance of fitting under the limit anyway. That is a
rate limiter (a token bucket), next to the concurrency semaphore.
