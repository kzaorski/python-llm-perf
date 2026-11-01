#!/usr/bin/env python3
"""Przebieg pomiarowy: k6 + próbkowanie stanu aplikacji i atrapy → wyniki/<NAZWA>-przebieg.json.

    python scripts/pomiar.py ex12-mieszany --dopływ-s 180 -- run -o experimental-prometheus-rw /scripts/mieszany.js
    python scripts/pomiar.py ex10-dlugie --profil dlugi-ttft-ping -- run /scripts/dlugie.js -e N=4 -e TTFT_MS=90000

Co 2 s zapisuje: kolejkę aplikacji per klasa (czekające, w toku, wiek najstarszego — GET /diag),
stan atrapy (generacje w toku, kolejka dostawcy, wiek najstarszej generacji — GET /admin/stats).
Na koniec: zaległość w chwili końca dopływu (`--dopływ-s`), czas opróżnienia (drain) po końcu dopływu,
przyrosty odpowiedzi atrapy wg statusu (w tym porzucone `cancelled_*`) i wyniki aplikacji wg klasy.
Podsumowanie k6 (tempo, dropped_iterations, czasy z Server-Timing) zapisuje sam k6: wyniki/<NAZWA>.json.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.environ.get("APP_URL_HOST", "http://127.0.0.1:8060")
MOCK = os.environ.get("MOCK_URL_HOST", "http://127.0.0.1:8061")


def _get(url: str, metoda: str = "GET"):
    try:
        req = urllib.request.Request(url, method=metoda)
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read())
    except Exception as e:  # noqa: BLE001 — próbkowanie nie może przerwać pomiaru
        return {"_blad": f"{type(e).__name__}: {e}"}


def _wyniki_app(diag: dict) -> dict:
    out: dict = {}
    for w in diag.get("wyniki", []):
        out.setdefault(w["klasa"], {}).setdefault(w["wynik"], 0)
        out[w["klasa"]][w["wynik"]] += w["n"]
    return out


def _roznica(a: dict, b: dict) -> dict:
    out = {}
    for k in set(a) | set(b):
        if isinstance(b.get(k), dict) or isinstance(a.get(k), dict):
            out[k] = _roznica(a.get(k, {}) or {}, b.get(k, {}) or {})
        else:
            d = (b.get(k) or 0) - (a.get(k) or 0)
            if d:
                out[k] = d
    return out


def main() -> None:
    if "--" not in sys.argv:
        sys.exit(__doc__)
    i = sys.argv.index("--")
    ap = argparse.ArgumentParser()
    ap.add_argument("nazwa")
    ap.add_argument("--dopływ-s", dest="doplyw", type=float, default=None, help="czas dopływu ruchu (koniec = t)")
    ap.add_argument("--profil", default=None, help="profil atrapy ustawiany przed testem (POST /admin/profile)")
    ap.add_argument("--drain-max-s", type=float, default=600)
    a = ap.parse_args(sys.argv[1:i])
    k6_args = sys.argv[i + 1:]

    if a.profil:
        _get(f"{MOCK}/admin/profile/{a.profil}", "POST")
    mock0 = _get(f"{MOCK}/admin/stats")
    app0 = _get(f"{APP}/diag")
    probki: list[dict] = []
    stop = threading.Event()
    t0 = time.time()

    def probkuj():
        while not stop.is_set():
            d = _get(f"{APP}/diag")
            m = _get(f"{MOCK}/admin/stats")
            probki.append({"t": round(time.time() - t0, 1), "app": d.get("kolejka"),
                           "mock": {p: {k: v.get(k) for k in ("generating", "waiting", "oldest_inflight_s")}
                                    for p, v in m.items() if isinstance(v, dict)}})
            stop.wait(2.0)

    th = threading.Thread(target=probkuj, daemon=True)
    th.start()
    cmd = ["docker", "compose", "run", "--rm", "-e", f"WYNIK={a.nazwa}", "k6", *k6_args]
    print("$", " ".join(cmd), flush=True)
    rc = subprocess.call(cmd, cwd=REPO)
    t_k6 = time.time() - t0
    # po zakończeniu k6 czekamy, aż aplikacja i atrapa opróżnią kolejki (praca „po nikogo")
    while time.time() - t0 < t_k6 + a.drain_max_s:
        d = _get(f"{APP}/diag").get("kolejka") or {}
        m = _get(f"{MOCK}/admin/stats")
        zajete = sum(v.get("czekajace", 0) + v.get("w_toku", 0) for v in d.values()) + \
            sum((v.get("generating") or 0) + (v.get("waiting") or 0) for v in m.values() if isinstance(v, dict))
        if zajete == 0:
            break
        time.sleep(2)
    time.sleep(2.5)
    stop.set()
    th.join()

    mock1 = _get(f"{MOCK}/admin/stats")
    app1 = _get(f"{APP}/diag")
    raport = {"nazwa": a.nazwa, "start": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0)),
              "k6_rc": rc, "k6_czas_s": round(t_k6, 1), "dopływ_s": a.doplyw, "profil": a.profil,
              "atrapa_przyrost": {p: _roznica(mock0.get(p, {}).get("responses", {}), mock1.get(p, {}).get("responses", {}))
                                  for p in ("a", "b")},
              "app_wyniki_przyrost": _roznica(_wyniki_app(app0), _wyniki_app(app1)),
              "app_proby_http": app1.get("proby_http"), "probki": probki}
    if a.doplyw is not None:
        po = [p for p in probki if p["t"] >= a.doplyw]
        if po:
            raport["zaleglosc_na_koniec_doplywu"] = {"t": po[0]["t"], "app": po[0]["app"], "mock": po[0]["mock"]}
        def pusto(p):
            ap_ = p.get("app") or {}
            mk = p.get("mock") or {}
            return all((v or {}).get("czekajace", 0) + (v or {}).get("w_toku", 0) == 0 for v in ap_.values()) and \
                all((v.get("generating") or 0) + (v.get("waiting") or 0) == 0 for v in mk.values())
        koniec = next((p["t"] for p in po if pusto(p)), None)
        raport["drain_po_koncu_doplywu_s"] = round(koniec - a.doplyw, 1) if koniec is not None else None
    os.makedirs(os.path.join(REPO, "wyniki"), exist_ok=True)
    plik = os.path.join(REPO, "wyniki", f"{a.nazwa}-przebieg.json")
    with open(plik, "w") as f:
        json.dump(raport, f, ensure_ascii=False, indent=1)
    skrot = {k: v for k, v in raport.items() if k != "probki"}
    print(json.dumps(skrot, ensure_ascii=False, indent=1))
    print("zapisano", plik)
    sys.exit(rc)


if __name__ == "__main__":
    main()
