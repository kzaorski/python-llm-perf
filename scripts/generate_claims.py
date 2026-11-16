"""Generator of synthetic insurance claims (EN) — deterministic (seed), a large dataset.

Usage:   python scripts/generate_claims.py [--n 20000] [--seed 20261031] [--k6 2000]
Output:  data/claims.jsonl  (the full dataset for the app/worker)
         data/k6_claims.json (a sample for the k6 SharedArray: id, type, description)

The length of the descriptions is deliberately varied (short / medium / long), so that the number of input
tokens — and therefore TTFT and ITPM limit usage — differs between claims. The same
seed gives byte-for-byte the same file (check: shasum data/claims.jsonl).
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path

FIRST_NAMES = "Mary Patricia Jennifer Linda Barbara Susan Karen Nancy Lisa Sarah Emily Laura " \
              "James John Robert Michael William David Richard Thomas Daniel Matthew Andrew Joseph Steven Peter".split()
LAST_NAMES = "Smith Johnson Williams Brown Jones Miller Davis Wilson Anderson Taylor " \
             "Hall Moore Martin Jackson Thompson White Harris Clark Lewis Walker".split()
CITIES = "Springfield Riverside Fairview Georgetown Madison Franklin Clinton Greenville Salem Bristol Dayton Auburn " \
         "Oxford Newport Milton Hudson Ashland Dover Lexington Burlington Arlington".split()
STREETS = "Oak Maple Cedar Pine Elm Walnut Birch Willow Lincoln Washington Jefferson Station".split()
CHANNELS = ["email", "phone", "portal", "app", "agent"]
TYPES = {
    "COMPREHENSIVE": 0.34, "LIABILITY": 0.22, "HOME": 0.24, "ACCIDENT": 0.08, "TRAVEL": 0.07, "OTHER": 0.05,
}
CARS = ["Skoda Octavia", "Toyota Corolla", "Volkswagen Golf", "Opel Astra", "Kia Ceed", "Dacia Duster",
        "Ford Focus", "Hyundai i30", "Renault Clio", "BMW 320d", "Audi A4", "Fiat Tipo"]
EVENTS = {
    "COMPREHENSIVE": ["an unknown driver damaged the {part} in a parking lot on {street} Street",
                      "during a hailstorm the {part} and the hood were dented",
                      "while backing out of a parking space I hit a post, damaging the {part}",
                      "the car was stolen from outside my building at night, police opened a case"],
    "LIABILITY": ["the driver of another car failed to give way to me at an intersection and hit the {part}",
                  "the at-fault driver rear-ended my car at a traffic light, damaging the {part}",
                  "when changing lanes the other driver scraped the {part}"],
    "HOME": ["the upstairs neighbor flooded the bathroom and kitchen, ruining the ceiling",
             "a pipe under the sink burst, water flooded the kitchen and hallway floors",
             "there was a break-in, a laptop, jewelry and a bike were stolen",
             "an electrical short circuit caused a fire in the living room"],
    "ACCIDENT": ["I slipped on an icy sidewalk outside my house and broke my wrist",
                 "I tore a ligament in my knee during a training session",
                 "my child broke an arm on the school playground"],
    "TRAVEL": ["my luggage did not arrive, the airline confirmed it was lost",
               "the flight was cancelled, so I paid for an extra hotel night",
               "I fell ill while traveling abroad and had to use a private clinic"],
    "OTHER": ["a tree fell over onto the fence during a windstorm",
              "my phone, covered by device insurance, was damaged",
              "I report damage to my crops after a storm"],
}
PARTS = ["left door", "right door", "front bumper", "rear bumper", "fender", "side mirror", "hood", "headlight"]
FOLLOW_UPS = [
    "Photos and the policy number are attached.",
    "Please call me as soon as possible, because I need my car for work.",
    "The police came to the scene, and I have their report.",
    "A neighbor witnessed the incident and can confirm what happened.",
    "Please let me know which documents I still need to provide.",
    "I would like to use direct repair at one of your partner repair shops.",
    "Please provide a rental car during the repair.",
    "I disagree with the appraiser's earlier estimate and request a new inspection.",
    "The damage happened while I was away, and I noticed it only after I returned.",
    "Enclosed are the invoices for the damaged items I purchased.",
    "Please confirm by email that you received the claim.",
    "This is my second claim this year, so please tell me how it affects the premium.",
]


def describe(rng: random.Random, claim_type: str) -> str:
    event = rng.choice(EVENTS[claim_type]).format(part=rng.choice(PARTS), street=rng.choice(STREETS))
    # length distribution: 50% short (0-1 follow-ups), 35% medium (2-4), 15% long (6-12)
    u = rng.random()
    k = rng.randint(0, 1) if u < 0.5 else rng.randint(2, 4) if u < 0.85 else rng.randint(6, 12)
    sentences = [f"On {{date}} {event}."] + [rng.choice(FOLLOW_UPS) for _ in range(k)]
    return " ".join(sentences)


def generate(n: int, seed: int):
    rng = random.Random(seed)
    types, weights = zip(*TYPES.items())
    start = date(2026, 1, 1)
    for i in range(1, n + 1):
        claim_type = rng.choices(types, weights)[0]
        d = start + timedelta(days=rng.randrange(0, 300))
        first_name, last_name = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        customer = f"{first_name} {last_name}"
        rec = {
            "id": f"CLM/2026/{i:06d}",
            "type": claim_type,
            "incident_date": d.isoformat(),
            "reported_date": (d + timedelta(days=rng.randint(0, 14))).isoformat(),
            "customer": customer,
            "policy": f"{claim_type[:2]}-{rng.randint(100000, 999999)}",
            "city": rng.choice(CITIES),
            "channel": rng.choice(CHANNELS),
            "vehicle": rng.choice(CARS) if claim_type in ("COMPREHENSIVE", "LIABILITY") else None,
            "estimated_amount_usd": round(rng.lognormvariate(8.3, 0.9), 2),
            "description": describe(rng, claim_type).replace("{date}", d.strftime("%m/%d/%Y")),
        }
        yield rec


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=20261031)
    ap.add_argument("--k6", type=int, default=2000, help="how many claims in the k6 sample")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "data"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    sample, n_chars = [], 0
    with open(out / "claims.jsonl", "w", encoding="utf-8") as f:
        for rec in generate(a.n, a.seed):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n_chars += len(rec["description"])
            if len(sample) < a.k6:
                sample.append({"id": rec["id"], "type": rec["type"], "description": rec["description"]})
    (out / "k6_claims.json").write_text(json.dumps(sample, ensure_ascii=False), encoding="utf-8")
    print(f"saved {a.n} claims → {out / 'claims.jsonl'} (avg description {n_chars / a.n:.0f} characters); "
          f"k6 sample: {len(sample)} → {out / 'k6_claims.json'}")


if __name__ == "__main__":
    main()
