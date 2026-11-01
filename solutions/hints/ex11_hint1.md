# Ćw. 11 — podpowiedź 1 (kierunek)

Gdy dostawca `a` milczy, każde żądanie najpierw czeka na jego timeout, a dopiero potem idzie do `b`.
Potrzebujesz pamięci: „`a` ostatnio zawodzi — przez chwilę nie pytaj go wcale”, a co jakiś czas jedno
żądanie-próbka sprawdza, czy wrócił. To wyłącznik (circuit breaker) z trzema stanami.
