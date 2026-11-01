# Ćw. 11 — podpowiedź 2 (API)

Stany: `zamkniety` (ruch do `a`, licz kolejne awarie) → po `CB_PROG` (5) awariach `otwarty` na
`CB_OTWARCIE_S` (30 s; wszystko od razu do `b`) → `polotwarty` (jedna próbka do `a`: sukces zamyka, porażka
otwiera ponownie). Atrybut `llm.cb.stan` na spanie `llm.call` (TraceQL `{span.llm.cb.stan="otwarty"}`),
zmiany stanu w `/diag` (`wyniki` z `endpoint == "cb"`). Dowód: `sum by (provider) (increase(mock_llm_requests_total[2m]))`.
