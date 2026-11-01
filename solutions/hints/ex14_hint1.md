# Ćw. 14 — podpowiedź 1 (kierunek)

Dwie rzeczy: (1) metryka — `XLEN` liczy wszystkie wpisy w strumieniu, również przetworzone; długość kolejki
opisuje **grupa konsumentów** (co nieodebrane, co w toku); (2) współbieżność — worker przyjmuje 2 × 100
zadań naraz, a dostawca ma moc 8. Dlaczego przy takim workerze kolejka wygląda na pustą?
