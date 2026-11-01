# Ćw. 07 — podpowiedź 1 (kierunek)

Worker sync gunicorna obsługuje jedno żądanie naraz. Aplikacja czeka na I/O (LLM), nie liczy — więc
przepustowość = liczba procesów / czas wywołania, a każdy proces kosztuje kilkadziesiąt MB. Do tego
domyślny `--timeout 30` zabija worker przy dłuższym wywołaniu. Jaki typ workera obsłuży setki czekających
żądań w jednym procesie?
