# Ćw. 06 — podpowiedź 1 (kierunek)

Żądanie czeka 30–60 s, choć samo wywołanie LLM trwa 1 s, a atrapa jest prawie bezczynna. Zasób, na który
się czeka, jest po naszej stronie. Policz z Little'a, ile wywołań naraz potrzeba przy 20/s i ~1 s, i porównaj
z liczbą slotów aplikacji. Sprawdź też drugi „ukryty” limit: pulę połączeń klienta HTTP.
