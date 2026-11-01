# Ćw. 03 — podpowiedź 1 (kierunek)

Prawo Little'a: L = λ·W. L — średnio ile żądań jest „w środku” (tu: zajętych slotów), λ — przepustowość,
W — czas obsługi. Gdy L dojdzie do liczby slotów, λ przestaje rosnąć, a nadwyżka dopływu ląduje w kolejce —
to kolano krzywej. Szukaj chwili, w której `llm_inflight` przykleja się do maksimum, a czekanie zaczyna rosnąć.
