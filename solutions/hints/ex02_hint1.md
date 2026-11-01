# Ćw. 02 — podpowiedź 1 (kierunek)

Model zamknięty: liczba „użytkowników” (VU) jest stała, każdy czeka na odpowiedź, zanim wyśle następne
żądanie — tempo zależy od systemu. Model otwarty: żądania przychodzą w zadanym tempie niezależnie od tego,
czy poprzednie się skończyły. W k6 to różnica **executora** scenariusza, nie kodu funkcji `default`.
