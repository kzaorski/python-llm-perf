#!/usr/bin/env python3
"""A measurement run: k6 + sampling the state of the app and the mock → results/<NAME>-run.json.

    python scripts/measure.py ex12-mixed --inflow-s 180 -- run -o experimental-prometheus-rw /scripts/mixed.js
    python scripts/measure.py ex10-long --profile long-ttft-ping -- run /scripts/long.js -e N=4 -e TTFT_MS=90000

Every 2 s it records: the app queue per class (waiting, in flight, age of the oldest — GET /diag),
the mock state (generations in flight, the provider queue, the age of the oldest generation — GET /admin/stats).
At the end: the backlog at the moment inflow ends (`--inflow-s`), the drain time after inflow ends,
the mock response deltas by status (including abandoned `cancelled_*`) and the app outcomes by class.
The k6 summary (rate, dropped_iterations, Server-Timing times) is written by k6 itself: results/<NAME>.json.
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


def _get(url: str, method: str = "GET"):
    try:
        req = urllib.request.Request(url, method=method)
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read())
    except Exception as e:  # noqa: BLE001 — sampling must not abort the measurement
        return {"_error": f"{type(e).__name__}: {e}"}


def _app_outcomes(diag: dict) -> dict:
    out: dict = {}
    for w in diag.get("outcomes", []):
        out.setdefault(w["request_class"], {}).setdefault(w["outcome"], 0)
        out[w["request_class"]][w["outcome"]] += w["n"]
    return out


def _diff(a: dict, b: dict) -> dict:
    out = {}
    for k in set(a) | set(b):
        if isinstance(b.get(k), dict) or isinstance(a.get(k), dict):
            out[k] = _diff(a.get(k, {}) or {}, b.get(k, {}) or {})
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
    ap.add_argument("name")
    ap.add_argument("--inflow-s", dest="inflow", type=float, default=None, help="traffic inflow time (end = t)")
    ap.add_argument("--profile", default=None, help="mock profile set before the test (POST /admin/profile)")
    ap.add_argument("--drain-max-s", type=float, default=600)
    a = ap.parse_args(sys.argv[1:i])
    k6_args = sys.argv[i + 1:]

    if a.profile:
        _get(f"{MOCK}/admin/profile/{a.profile}", "POST")
    mock0 = _get(f"{MOCK}/admin/stats")
    app0 = _get(f"{APP}/diag")
    samples: list[dict] = []
    stop = threading.Event()
    t0 = time.time()

    def sample():
        while not stop.is_set():
            d = _get(f"{APP}/diag")
            m = _get(f"{MOCK}/admin/stats")
            samples.append({"t": round(time.time() - t0, 1), "app": d.get("queue"),
                            "mock": {p: {k: v.get(k) for k in ("generating", "waiting", "oldest_inflight_s")}
                                     for p, v in m.items() if isinstance(v, dict)}})
            stop.wait(2.0)

    th = threading.Thread(target=sample, daemon=True)
    th.start()
    cmd = ["docker", "compose", "run", "--rm", "-e", f"RESULT={a.name}", "k6", *k6_args]
    print("$", " ".join(cmd), flush=True)
    rc = subprocess.call(cmd, cwd=REPO)
    t_k6 = time.time() - t0
    # after k6 finishes we wait for the app and the mock to drain their queues (work "for nobody")
    while time.time() - t0 < t_k6 + a.drain_max_s:
        d = _get(f"{APP}/diag").get("queue") or {}
        m = _get(f"{MOCK}/admin/stats")
        busy = sum(v.get("waiting", 0) + v.get("inflight", 0) for v in d.values()) + \
            sum((v.get("generating") or 0) + (v.get("waiting") or 0) for v in m.values() if isinstance(v, dict))
        if busy == 0:
            break
        time.sleep(2)
    time.sleep(2.5)
    stop.set()
    th.join()

    mock1 = _get(f"{MOCK}/admin/stats")
    app1 = _get(f"{APP}/diag")
    report = {"name": a.name, "start": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0)),
              "k6_rc": rc, "k6_duration_s": round(t_k6, 1), "inflow_s": a.inflow, "profile": a.profile,
              "mock_delta": {p: _diff(mock0.get(p, {}).get("responses", {}), mock1.get(p, {}).get("responses", {}))
                             for p in ("a", "b")},
              "app_outcomes_delta": _diff(_app_outcomes(app0), _app_outcomes(app1)),
              "app_http_attempts": app1.get("http_attempts"), "samples": samples}
    if a.inflow is not None:
        after = [p for p in samples if p["t"] >= a.inflow]
        if after:
            report["backlog_at_inflow_end"] = {"t": after[0]["t"], "app": after[0]["app"], "mock": after[0]["mock"]}

        def is_empty(p):
            app_q = p.get("app") or {}
            mk = p.get("mock") or {}
            return all((v or {}).get("waiting", 0) + (v or {}).get("inflight", 0) == 0 for v in app_q.values()) and \
                all((v.get("generating") or 0) + (v.get("waiting") or 0) == 0 for v in mk.values())
        end = next((p["t"] for p in after if is_empty(p)), None)
        report["drain_after_inflow_end_s"] = round(end - a.inflow, 1) if end is not None else None
    os.makedirs(os.path.join(REPO, "results"), exist_ok=True)
    file = os.path.join(REPO, "results", f"{a.name}-run.json")
    with open(file, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    summary = {k: v for k, v in report.items() if k != "samples"}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print("saved", file)
    sys.exit(rc)


if __name__ == "__main__":
    main()
