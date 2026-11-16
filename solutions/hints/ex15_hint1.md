# Ex. 15 — hint 1 (direction)

All 50 requests check the cache at the same moment — all of them see "missing" and each computes on its own. You need a
mechanism of "somebody is already computing this key — wait for their result". Within one process a shared awaitable
object is enough; across processes — a lock in Redis.
