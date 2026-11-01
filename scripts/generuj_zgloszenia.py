"""Generator syntetycznych zgłoszeń szkodowych (PL) — deterministyczny (ziarno), duży zbiór.

Użycie:  python scripts/generuj_zgloszenia.py [--n 20000] [--seed 20261031] [--k6 2000]
Wynik:   data/zgloszenia.jsonl  (pełny zbiór dla aplikacji/workera)
         data/k6_zgloszenia.json (próbka dla k6 SharedArray: id, typ, opis)

Długość opisów jest celowo zróżnicowana (krótkie / średnie / długie), żeby liczba tokenów
wejścia — a więc TTFT i zużycie limitu ITPM — różniła się między zgłoszeniami. Ten sam
seed daje bajt w bajt ten sam plik (sprawdź: shasum data/zgloszenia.jsonl).
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path

IMIONA = "Anna Maria Katarzyna Małgorzata Agnieszka Barbara Ewa Krystyna Elżbieta Zofia Joanna Magdalena " \
         "Piotr Krzysztof Andrzej Tomasz Jan Paweł Michał Marcin Grzegorz Józef Łukasz Adam Zbigniew Jakub".split()
NAZWISKA = "Nowak Kowalski Wiśniewski Wójcik Kowalczyk Kamiński Lewandowski Zieliński Szymański Woźniak " \
           "Dąbrowski Kozłowski Jankowski Mazur Kwiatkowski Krawczyk Piotrowski Grabowski Nowakowski Pawłowski".split()
MIASTA = "Warszawa Kraków Łódź Wrocław Poznań Gdańsk Szczecin Bydgoszcz Lublin Białystok Katowice Gdynia " \
         "Częstochowa Radom Toruń Rzeszów Kielce Olsztyn Opole Zielona Góra".split()
ULICE = "Lipowej Polnej Leśnej Słonecznej Krótkiej Szkolnej Ogrodowej Kwiatowej Długiej Kościuszki Mickiewicza Kolejowej".split()
KANALY = ["email", "telefon", "portal", "aplikacja", "agent"]
TYPY = {
    "AC": 0.34, "OC": 0.22, "MIESZKANIE": 0.24, "NNW": 0.08, "PODROZ": 0.07, "INNE": 0.05,
}
AUTA = ["Skoda Octavia", "Toyota Corolla", "Volkswagen Golf", "Opel Astra", "Kia Ceed", "Dacia Duster",
        "Ford Focus", "Hyundai i30", "Renault Clio", "BMW 320d", "Audi A4", "Fiat Tipo"]
ZDARZENIA = {
    "AC": ["nieznany sprawca uszkodził {czesc} na parkingu przy ul. {ulica}",
           "podczas gradobicia zostały wgniecione {czesc} i maska",
           "w czasie manewru cofania uderzyłem w słupek, uszkadzając {czesc}",
           "pojazd został skradziony sprzed bloku w nocy, policja wszczęła postępowanie"],
    "OC": ["kierowca innego pojazdu nie ustąpił mi pierwszeństwa na skrzyżowaniu i uderzył w {czesc}",
           "sprawca najechał na tył mojego auta na światłach, uszkadzając {czesc}",
           "podczas zmiany pasa ruchu sprawca zarysował {czesc}"],
    "MIESZKANIE": ["sąsiad z góry zalał łazienkę i kuchnię, zniszczony sufit i panele",
                   "pękła rura pod zlewem, woda zalała podłogę w kuchni i przedpokoju",
                   "doszło do włamania, skradziono laptop, biżuterię i rower",
                   "zwarcie instalacji elektrycznej spowodowało pożar w salonie"],
    "NNW": ["poślizgnąłem się na oblodzonym chodniku i złamałem nadgarstek",
            "podczas treningu doszło do zerwania więzadła w kolanie",
            "dziecko złamało rękę na placu zabaw w szkole"],
    "PODROZ": ["bagaż nie dotarł na miejsce, przewoźnik potwierdził zagubienie",
               "lot został odwołany, poniosłam koszty dodatkowego noclegu",
               "zachorowałem za granicą i musiałem skorzystać z prywatnej kliniki"],
    "INNE": ["drzewo przewróciło się na ogrodzenie podczas wichury",
             "uszkodzeniu uległ telefon objęty ubezpieczeniem sprzętu",
             "zgłaszam szkodę w uprawach po ulewie"],
}
CZESCI = ["lewe drzwi", "prawe drzwi", "przedni zderzak", "tylny zderzak", "błotnik", "lusterko", "maskę", "reflektor"]
DOPOWIEDZENIA = [
    "Dołączam zdjęcia uszkodzeń oraz numer polisy.",
    "Proszę o pilny kontakt telefoniczny, bo pojazd jest mi potrzebny do pracy.",
    "Na miejscu była policja, mam notatkę z interwencji.",
    "Świadkiem zdarzenia był sąsiad, który może potwierdzić przebieg.",
    "Proszę o informację, jakie dokumenty muszę jeszcze dostarczyć.",
    "Chciałbym skorzystać z naprawy bezgotówkowej w warsztacie partnerskim.",
    "Proszę o samochód zastępczy na czas naprawy.",
    "Nie zgadzam się z wcześniejszą wyceną rzeczoznawcy i proszę o ponowne oględziny.",
    "Szkoda powstała w czasie mojego wyjazdu, zauważyłem ją dopiero po powrocie.",
    "W załączeniu przesyłam faktury za zakup uszkodzonych rzeczy.",
    "Proszę o potwierdzenie przyjęcia zgłoszenia mailem.",
    "To moja druga szkoda w tym roku, proszę o informację o wpływie na składkę.",
]


def opis(rng: random.Random, typ: str) -> str:
    zd = rng.choice(ZDARZENIA[typ]).format(czesc=rng.choice(CZESCI), ulica=rng.choice(ULICE))
    # rozkład długości: 50% krótkie (0-1 dopowiedzeń), 35% średnie (2-4), 15% długie (6-12)
    u = rng.random()
    k = rng.randint(0, 1) if u < 0.5 else rng.randint(2, 4) if u < 0.85 else rng.randint(6, 12)
    zdania = [f"Dnia {{data}} {zd}."] + [rng.choice(DOPOWIEDZENIA) for _ in range(k)]
    return " ".join(zdania)


def generuj(n: int, seed: int):
    rng = random.Random(seed)
    typy, wagi = zip(*TYPY.items())
    start = date(2026, 1, 1)
    for i in range(1, n + 1):
        typ = rng.choices(typy, wagi)[0]
        d = start + timedelta(days=rng.randrange(0, 300))
        imie, nazwisko = rng.choice(IMIONA), rng.choice(NAZWISKA)
        if imie.endswith("a") and nazwisko.endswith("ki"):
            nazwisko = nazwisko[:-1] + "a"  # Kowalski → Kowalska
        klient = f"{imie} {nazwisko}"
        rec = {
            "id": f"SZK/2026/{i:06d}",
            "typ": typ,
            "data_zdarzenia": d.isoformat(),
            "data_zgloszenia": (d + timedelta(days=rng.randint(0, 14))).isoformat(),
            "klient": klient,
            "polisa": f"{typ[:2]}-{rng.randint(100000, 999999)}",
            "miasto": rng.choice(MIASTA),
            "kanal": rng.choice(KANALY),
            "pojazd": rng.choice(AUTA) if typ in ("AC", "OC") else None,
            "kwota_szacowana_pln": round(rng.lognormvariate(8.3, 0.9), 2),
            "opis": opis(rng, typ).replace("{data}", d.strftime("%d.%m.%Y")),
        }
        yield rec


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=20261031)
    ap.add_argument("--k6", type=int, default=2000, help="ile zgłoszeń w próbce dla k6")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "data"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    sample, n_chars = [], 0
    with open(out / "zgloszenia.jsonl", "w", encoding="utf-8") as f:
        for rec in generuj(a.n, a.seed):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n_chars += len(rec["opis"])
            if len(sample) < a.k6:
                sample.append({"id": rec["id"], "typ": rec["typ"], "opis": rec["opis"]})
    (out / "k6_zgloszenia.json").write_text(json.dumps(sample, ensure_ascii=False), encoding="utf-8")
    print(f"zapisano {a.n} zgłoszeń → {out / 'zgloszenia.jsonl'} (śr. opis {n_chars / a.n:.0f} znaków); "
          f"próbka k6: {len(sample)} → {out / 'k6_zgloszenia.json'}")


if __name__ == "__main__":
    main()
