#!/usr/bin/env python3
"""The solutions overlay: a copy of the app in the "after exercise NN" state — without touching your app/.

    python scripts/overlay.py --after 12                 # app/ + solutions/exKK_* (KK ≤ 12) → .run/after-12/
    python scripts/overlay.py --after 18 --flaws F3,F10  # the final state with flaws restored (incident)
    python scripts/overlay.py --after 12 --target .run/x # your own target directory

Running the copy (e.g. on port 8060, when your app is stopped):
    uvicorn --app-dir .run/after-12 app.main:app --port 8060

For each module we take the LATEST cumulative solution numbered ≤ NN (e.g. limiter: ex01 → ex06 →
ex08 → ex12). `--flaws` rolls the given modules back to the version from before the exercise that removes that flaw.
Used by: smoke.sh (the `check.py --all` regression on solutions) and incident.sh (the final).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# solution module → file in the app
MODULES = {
    "limiter": "app/llm/limiter.py", "client": "app/llm/client.py", "call": "app/llm/call.py",
    "retries": "app/llm/retries.py", "fallback": "app/llm/fallback.py",
    "overload": "app/overload.py", "classification": "app/classification.py", "templates": "app/templates.py",
    "stream": "app/stream.py", "tasks": "app/tasks.py", "queue_metrics": "app/queue_metrics.py",
    "cache": "app/cache.py", "batch": "app/batch.py", "gunicorn": "gunicorn.conf.py",
}
# flaw → (module, the exercise that removes it)
FLAWS = {
    "F1": ("classification", 4), "F2": ("templates", 5), "F3": ("limiter", 6), "F4": ("limiter", 8),
    "F5": ("retries", 9), "F6": ("client", 10), "F7": ("overload", 12), "F8": ("overload", 12),
    "F9": ("stream", 13), "F10": ("cache", 15), "F11": ("batch", 16), "F12": ("fallback", 11),
    "F13": ("gunicorn", 7), "F15": ("tasks", 14), "F16": ("call", 10), "F17": ("client", 10),
    "F18": ("limiter", 12),
}
# flaws whose fix changes more than one module: additional modules rolled back together with the main one
# (F5: ex. 09 also changes client.py — `max_retries=0`; without it a rolled-back F5 does not multiply attempts through the SDK)
EXTRA_FLAWS = {"F5": [("client", 9)]}
_PATTERN = re.compile(r"^ex(\d\d)_(\w+?)\.(py)$")


def solutions() -> dict[str, list[tuple[int, str]]]:
    out: dict[str, list[tuple[int, str]]] = {}
    for f in sorted(os.listdir(os.path.join(REPO, "solutions"))):
        m = _PATTERN.match(f)
        if m and m.group(2) in MODULES:
            out.setdefault(m.group(2), []).append((int(m.group(1)), f))
    return out


def plan(after: int, flaws: list[str]) -> dict[str, str | None]:
    """module → solution file (None = the version from app/ stays, i.e. the skeleton)."""
    sols = solutions()
    limit = {m: after for m in MODULES}
    for w in flaws:
        for mod, exercise_no in [FLAWS[w], *EXTRA_FLAWS.get(w, [])]:
            limit[mod] = min(limit[mod], exercise_no - 1)
    out = {}
    for mod in MODULES:
        candidates = [f for n, f in sols.get(mod, []) if n <= limit[mod]]
        out[mod] = candidates[-1] if candidates else None
    return out


def build(after: int, flaws: list[str], target: str) -> dict:
    target = os.path.abspath(target)
    if os.path.exists(target):
        shutil.rmtree(target)
    os.makedirs(target)
    shutil.copytree(os.path.join(REPO, "app"), os.path.join(target, "app"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(os.path.join(REPO, "gunicorn.conf.py"), os.path.join(target, "gunicorn.conf.py"))
    os.symlink(os.path.join(REPO, "data"), os.path.join(target, "data"))
    p = plan(after, flaws)
    for mod, file in p.items():
        if file:
            shutil.copy(os.path.join(REPO, "solutions", file), os.path.join(target, MODULES[mod]))
    return p


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--after", type=int, required=True, help="the state after exercise NN (1–18)")
    ap.add_argument("--flaws", default="", help="e.g. F3,F10 — restore these flaws in the --after state")
    ap.add_argument("--target", default=None, help="target directory (default .run/after-NN)")
    a = ap.parse_args()
    flaws = [w.strip().upper() for w in a.flaws.split(",") if w.strip()]
    unknown = [w for w in flaws if w not in FLAWS]
    if unknown:
        sys.exit(f"unknown flaws: {unknown}; known: {sorted(FLAWS)}")
    target = a.target or os.path.join(REPO, ".run", f"after-{a.after:02d}" + ("-" + "-".join(flaws) if flaws else ""))
    p = build(a.after, flaws, target)
    for mod, file in p.items():
        print(f"  {MODULES[mod]:24s} ← {file or '(skeleton from app/)'}")
    print(target)


if __name__ == "__main__":
    main()
