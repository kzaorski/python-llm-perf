# Ćw. 15 — podpowiedź 1 (kierunek)

Wszystkie 50 żądań sprawdza cache w tej samej chwili — wszystkie widzą „brak” i każde liczy samo. Potrzebujesz
mechanizmu „ktoś już liczy ten klucz — poczekaj na jego wynik”. W jednym procesie wystarczy wspólny obiekt
oczekiwania; między procesami — blokada w Redisie.
