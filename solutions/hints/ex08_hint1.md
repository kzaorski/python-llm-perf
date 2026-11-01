# Ćw. 08 — podpowiedź 1 (kierunek)

Dostawca mówi, ile Ci zostało: nagłówki `anthropic-ratelimit-*-remaining` / `-limit` / `-reset` w każdej
odpowiedzi i `retry-after` przy 429. Zamiast zbierać 429 i ponawiać, poczekaj **u siebie**, zanim wyślesz
wywołanie, na które limitu i tak nie ma. To limiter tempa (token bucket), obok semafora współbieżności.
