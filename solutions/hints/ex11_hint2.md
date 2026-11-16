# Ex. 11 — hint 2 (API)

States: `closed` (traffic to `a`, count consecutive failures) → after `CB_THRESHOLD` (5) failures `open` for
`CB_OPEN_S` (30 s; everything goes straight to `b`) → `half_open` (one probe request to `a`: success closes,
failure opens again). The `llm.cb.state` attribute on the `llm.call` span (TraceQL `{span.llm.cb.state="open"}`),
state changes in `/diag` (`outcomes` with `endpoint == "cb"`). Evidence:
`sum by (provider) (increase(mock_llm_requests_total[2m]))`.
