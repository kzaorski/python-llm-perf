# Ideas for extending the course

The course skills map as a roadmap — what else could be added as a flaw to diagnose or as an exercise.

| Idea | Diagnostic skill | Flaw / signal |
|---|---|---|
| Shared Redis rate limiter across processes | provider limits under horizontal scaling | 2 processes × their own bucket → 2× too much traffic, 429 despite the limiter (ex. 8, question 2) |
| Proxy (nginx) buffering responses in front of the app | buffering of the stream outside the app | `app_stream_first_chunk_seconds` OK, client TTFT ≈ the whole response (ex. 13, question 2) |
| Hedging (sending a second copy after p95) | latency tail vs cost | provider traffic +5–10%, p99 down; without a budget — amplification as in ex. 9 |
| Priorities in one pool (borrowing slots) | bulkhead vs utilization | ex. 12 bonus as a full exercise with a drain measurement |
| Long analyses through the task queue with a task deadline | task queue + age of the oldest entry as an SLO | ex. 14 bonus: the age of the oldest entry grows without a limit instead of a 503 |
| Autoscaling workers on `queue_oldest_age_seconds` | capacity control | scaling on `lag` does not work with a large prefetch (F15) |
| Provider prompt caching | cost and TTFT with a repeated prefix | TTFT and input tokens with a shared system prompt (requires the real API) |
| Slot leak on an exception in the stream | releasing resources on error paths | `llm_inflight` grows after every broken stream and does not come back |
| SLO alerts (burn rate) on rejections and queue age | operational detection of overload | final bonus as a separate exercise |
