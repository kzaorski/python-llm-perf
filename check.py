#!/usr/bin/env python3
"""check.py — a machine check of the "definition of done" criteria of the python-llm-perf course exercises.

    python check.py 06          # one exercise
    python check.py --all       # all of them (the course regression)
    python check.py 04 06 09    # several
    python check.py ex06        # the same as 06 (the form used in the exercise text)

We check the BEHAVIOR of the running app (port 8060), not the code: short load probes (seconds),
the mock LLM API (/admin/stats), Tempo (a trace by a known trace id), the queue metrics (8063) and the k6
summary files in results/. check does not run multi-minute tests — exercises 10 and 12 have shortened probes
(x-mock-* headers), and it reads the results of your minute-long runs from results/ if they exist.
Probes that change the mock configuration restore it at the end (POST /admin/reset).

Variables: APP_URL (http://127.0.0.1:8060), MOCK_URL (http://127.0.0.1:8061), GUNICORN_URL (…:8062),
GRAFANA_URL (http://127.0.0.1:3060), WORKER_METRICS_URL (http://127.0.0.1:8063/metrics),
CHECK_LOOKBACK_H (24) — how old results/*.json files we accept.
Exit code: 0 = everything PASS/SKIP, 1 = at least one FAIL.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import sys
import time
import uuid

import httpx2

REPO = os.path.dirname(os.path.abspath(__file__))
APP = os.environ.get("APP_URL", "http://127.0.0.1:8060")
MOCK = os.environ.get("MOCK_URL", "http://127.0.0.1:8061")
GUNICORN = os.environ.get("GUNICORN_URL", "http://127.0.0.1:8062")
GRAFANA = os.environ.get("GRAFANA_URL", "http://127.0.0.1:3060")
WORKER_METRICS = os.environ.get("WORKER_METRICS_URL", "http://127.0.0.1:8063/metrics")
LOOKBACK_H = float(os.environ.get("CHECK_LOOKBACK_H", "24"))
AUTH = (os.environ.get("GRAFANA_USER", "admin"), os.environ.get("GRAFANA_PASSWORD", "admin"))


class Fail(Exception):
    pass


class Skip(Exception):
    pass


def expect(condition: bool, description: str) -> None:
    if not condition:
        raise Fail(description)


# ---------------------------------------------------------------- tools
def pct(xs, p):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return float("nan")
    k = (len(xs) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def server_timing(h: str | None) -> dict:
    out = {}
    for part in (h or "").split(","):
        if ";dur=" in part:
            k, v = part.strip().split(";dur=")
            out[k] = float(v) / 1000
    return out


def mock(path: str, method="GET", body=None, provider=None) -> dict:
    r = httpx2.request(method, MOCK + path, json=body, params={"provider": provider} if provider else None, timeout=5)
    r.raise_for_status()
    return r.json()


def mock_responses(p="a") -> dict:
    return mock("/admin/stats")[p]["responses"]


def diff(a: dict, b: dict) -> dict:
    return {k: b.get(k, 0) - a.get(k, 0) for k in set(a) | set(b) if b.get(k, 0) != a.get(k, 0)}


def mock_reset() -> None:
    try:
        mock("/admin/reset", "POST")
    except Exception:  # noqa: BLE001
        pass


async def _one(c, method, url, headers, timeout):
    t0 = time.perf_counter()
    try:
        r = await c.request(method, url, headers=headers, timeout=timeout)
        try:
            body = r.json()
        except Exception:  # noqa: BLE001
            body = None
        return {"status": r.status_code, "t": time.perf_counter() - t0,
                "st": server_timing(r.headers.get("server-timing")), "json": body}
    except Exception as e:  # noqa: BLE001
        return {"status": 0, "t": time.perf_counter() - t0, "st": {}, "json": None, "err": type(e).__name__}


async def _traffic(urls, method="POST", headers=None, timeout=60.0, rps=None):
    """Sends requests all at once (rps=None) or in the open model (rps requests/s, regardless of the responses)."""
    limits = httpx2.Limits(max_connections=5000, max_keepalive_connections=5000)
    async with httpx2.AsyncClient(limits=limits) as c:
        tasks = []
        t0 = time.perf_counter()
        for i, u in enumerate(urls):
            tasks.append(asyncio.create_task(_one(c, method, u, headers or {}, timeout)))
            if rps:
                await asyncio.sleep(max(0.0, t0 + (i + 1) / rps - time.perf_counter()))
        return await asyncio.gather(*tasks)


def traffic(urls, **kw):
    return asyncio.run(_traffic(urls, **kw))


def claims(path: str, n: int, start: int | None = None) -> list[str]:
    s = start if start is not None else random.randint(1, 15000)
    return [f"{APP}/claims/{s + i}/{path}" for i in range(n)]


def statuses(w) -> dict:
    out: dict = {}
    for x in w:
        out[x["status"]] = out.get(x["status"], 0) + 1
    return out


def result_file(name: str) -> dict | None:
    p = os.path.join(REPO, "results", f"{name}.json")
    if not os.path.exists(p) or time.time() - os.path.getmtime(p) > LOOKBACK_H * 3600:
        return None
    with open(p) as f:
        return json.load(f)


def k6_metric(data: dict, name: str, stat: str):
    return ((data.get("metrics") or {}).get(name) or {}).get("values", {}).get(stat)


def require_app(drain_s: float = 45.0) -> None:
    """The app responds and has no backlog from earlier probes (otherwise the measurement would be unreliable)."""
    try:
        httpx2.get(APP + "/diag/ping", timeout=5).raise_for_status()
    except Exception as e:  # noqa: BLE001
        raise Fail(f"the app does not respond on {APP} ({type(e).__name__}) — run: uvicorn app.main:app --port 8060")
    t_end = time.time() + drain_s
    while True:
        try:
            k = httpx2.get(APP + "/diag", timeout=5).json()["queue"]
        except Exception:  # noqa: BLE001 — an older version of /diag: we do not check the backlog
            return
        busy = sum(v["waiting"] + v["inflight"] for v in k.values())
        if busy == 0:
            return
        if time.time() > t_end:
            raise Fail(f"the app has a backlog from earlier traffic ({k}) — work continues despite disconnected clients "
                       "(no cancellation, ex. 10?); restart the app and try again")
        time.sleep(2)


# ---------------------------------------------------------------- exercises
def ex01():
    """The request trace shows the slot wait time: the llm.queue_wait span + the llm.queue.wait_ms attribute."""
    require_app()
    trace_id = uuid.uuid4().hex
    tp = f"00-{trace_id}-{uuid.uuid4().hex[:16]}-01"
    r = httpx2.post(f"{APP}/claims/{random.randint(1, 20000)}/summary", headers={"traceparent": tp}, timeout=60)
    expect(r.status_code == 200, f"POST /summary → {r.status_code}")
    spans: list = []
    for _ in range(12):                      # export every ~5 s + Tempo ingest
        time.sleep(2.5)
        t = httpx2.get(f"{GRAFANA}/api/datasources/proxy/uid/tempo/api/traces/{trace_id}", auth=AUTH, timeout=10)
        if t.status_code == 200:
            spans = [s for b in t.json().get("batches", t.json().get("resourceSpans", []))
                     for ss in b.get("scopeSpans", b.get("instrumentationLibrarySpans", [])) for s in ss.get("spans", [])]
            if any(s["name"] == "llm.call" for s in spans):
                break
    names = sorted({s["name"] for s in spans})
    expect(spans, f"trace {trace_id} did not reach Tempo within 30 s (does the app send OTLP to :4368?)")
    expect("llm.queue_wait" in names, f"no llm.queue_wait span in the trace (found: {names})")
    attrs = {a["key"] for s in spans for a in s.get("attributes", [])}
    expect("llm.queue.wait_ms" in attrs, "no llm.queue.wait_ms attribute on the request span")
    wait_span = next(s for s in spans if s["name"] == "llm.queue_wait")
    call_parent = next((s.get("parentSpanId") for s in spans if s["name"] == "llm.call"), None)
    expect(call_parent != wait_span.get("spanId"), "llm.call is a child of llm.queue_wait — the wait should be a SIBLING")
    return f"trace {trace_id[:8]}…: spans {names}"


def ex02():
    """Both k6 runs (closed and open model) in results/, open p99 > closed, 0 dropped iterations."""
    z, o = result_file("ex02-closed"), result_file("ex02-open")
    expect(z is not None, "no results/ex02-closed.json — run k6/closed_model.js")
    expect(o is not None, "no results/ex02-open.json — run k6/open_model.js (fill in the scenario first)")
    p99_closed, p99_open = k6_metric(z, "http_req_duration", "p(99)"), k6_metric(o, "http_req_duration", "p(99)")
    drop = k6_metric(o, "dropped_iterations", "count") or 0
    expect(p99_closed and p99_open, "no http_req_duration p(99) in the summaries")
    expect(drop == 0, f"the open model dropped {drop} iterations (dropped_iterations) — too few VUs")
    expect(p99_open > 1.3 * p99_closed, f"open p99 {p99_open / 1000:.2f} s is not clearly > closed {p99_closed / 1000:.2f} s — "
                                        "did both runs have the same nominal intensity close to capacity?")
    return f"p99 closed {p99_closed / 1000:.2f} s, open {p99_open / 1000:.2f} s, dropped=0"


def ex03():
    """The ramp run (k6/ramp.js) saved: the achieved rate and the times after the steps."""
    r = result_file("ex03-ramp")
    expect(r is not None, "no results/ex03-ramp.json — run k6/ramp.js")
    n = k6_metric(r, "http_reqs", "count") or 0
    expect(n >= 200, f"the ramp has only {n} requests — run the full ramp")
    return f"ramp: {n} requests, p99 {k6_metric(r, 'http_req_duration', 'p(99)') / 1000:.2f} s"


def ex04():
    """Open traffic of 6/s on /classify for 10 s: the process keeps up, and /diag/ping responds right away (the loop is free)."""
    require_app()

    async def run():
        pings: list = []
        stop = asyncio.Event()

        async def ping_loop():
            async with httpx2.AsyncClient() as c:
                while not stop.is_set():
                    t0 = time.perf_counter()
                    try:
                        await c.get(APP + "/diag/ping", timeout=30)
                    except Exception:  # noqa: BLE001
                        pass
                    pings.append(time.perf_counter() - t0)
                    await asyncio.sleep(0.1)
        tp = asyncio.create_task(ping_loop())
        t0 = time.perf_counter()
        w = await _traffic(claims("classify", 60), rps=6, timeout=60)
        total = time.perf_counter() - t0
        stop.set()
        await tp
        return w, total, pings
    w, total, pings = asyncio.run(run())
    ok = sum(1 for x in w if x["status"] == 200)
    p99 = pct([x["t"] for x in w], 99)
    expect(pct(pings, 99) < 0.25, f"/diag/ping p99 {pct(pings, 99):.2f} s (max {max(pings):.1f} s) — the event loop is "
                                  f"blocked; /classify p99 {p99:.1f} s, the last response after {total:.0f} s")
    expect(ok == len(w) and total < 15, f"/classify: {ok}/{len(w)} OK, the last one after {total:.0f} s (inflow 10 s)")
    return f"/classify 6/s: p99 {p99:.2f} s, the last one after {total:.1f} s; /diag/ping p99 {pct(pings, 99) * 1000:.0f} ms"


def ex05():
    """60 concurrent /letter calls (each ~2.1 s on the mock) finish in one wave — without waiting for a pool thread (40)."""
    require_app()
    h = {"x-mock-ttft-ms": "2000", "x-mock-total-s": "0.1"}
    w = traffic(claims("letter", 60), headers=h, timeout=60)
    ts = [x["t"] for x in w if x["status"] == 200]
    expect(len(ts) == 60, f"only {len(ts)}/60 responses 200: {statuses(w)}")
    second_wave = sum(1 for t in ts if t > 1.5 * min(ts))
    expect(max(ts) < 1.5 * min(ts), f"{second_wave} of 60 requests waited for a second wave (min {min(ts):.2f} s, max {max(ts):.2f} s)"
                                    " — the handler occupies an anyio pool thread")
    return f"60× /letter: min {min(ts):.2f} s, max {max(ts):.2f} s (one wave)"


def ex06():
    """Open traffic of 20/s on /summary for 10 s: slot wait p99 < 0.5 s (the pool sized to λ·W)."""
    require_app()
    w = traffic(claims("summary", 200), rps=20, timeout=120)
    waits = [x["st"].get("wait") for x in w if x["status"] == 200]
    llm = [x["st"].get("llm") for x in w if x["status"] == 200]
    expect(len(waits) >= 190, f"only {len(waits)}/200 responses 200: {statuses(w)}")
    expect(pct(waits, 99) < 0.5, f"slot wait p50 {pct(waits, 50):.1f} s / p99 {pct(waits, 99):.1f} s with LLM service "
                                 f"p50 {pct(llm, 50):.2f} s — too few slots (L = λ·W)")
    return f"20/s: wait p99 {pct(waits, 99) * 1000:.0f} ms, LLM p50 {pct(llm, 50):.2f} s"


def ex07():
    """gunicorn with UvicornWorker (an ASGI app) runs on :8062, 32 concurrent requests in one wave."""
    try:
        h = httpx2.get(GUNICORN + "/health", timeout=5).json()
    except Exception as e:  # noqa: BLE001
        raise Fail(f"nothing responds on {GUNICORN} ({type(e).__name__}) — run: gunicorn -c gunicorn.conf.py")
    expect(h.get("server") == "gunicorn-uvicorn", f"/health on 8062 reports server={h.get('server')!r} "
                                                  "(expected gunicorn-uvicorn: UvicornWorker + app.main)")
    hdr = {"x-mock-ttft-ms": "2000", "x-mock-total-s": "0.1"}
    s = random.randint(1, 15000)
    # 32 = the slots of ONE process: the socket does not split connections evenly (question 3), so with 40 requests
    # one process sometimes got > 32 and some waited for a slot (smoke: 3 of 7 runs) — the probe should test
    # the process model, not luck in the connection split
    w = traffic([f"{GUNICORN}/claims/{s + i}/summary" for i in range(32)], headers=hdr, timeout=60)
    ts = [x["t"] for x in w if x["status"] == 200]
    expect(len(ts) == 32, f"{len(ts)}/32 responses 200: {statuses(w)}")
    expect(max(ts) < 3.5, f"32 requests of ~2.1 s: max {max(ts):.1f} s — requests wait for a free worker")
    return f"gunicorn-uvicorn: 32× max {max(ts):.2f} s"


def ex08():
    """The `limits` profile: 90 requests at once → the mock does not return 429 (a limiter on our side), all 200."""
    require_app()
    mock_reset()
    try:
        mock("/admin/profile/limits", "POST")
        a0 = mock_responses()
        inflight_max = [0]

        async def sample_and_send():
            async def sample():
                async with httpx2.AsyncClient() as c:
                    while True:
                        try:
                            k = (await c.get(APP + "/diag", timeout=5)).json()["queue"]["short"]
                            inflight_max[0] = max(inflight_max[0], k["inflight"])
                        except Exception:  # noqa: BLE001
                            pass
                        await asyncio.sleep(0.3)
            tp = asyncio.create_task(sample())
            r = await _traffic(claims("summary", 90), timeout=180)
            tp.cancel()
            return r
        w = asyncio.run(sample_and_send())
        d = diff(a0, mock_responses())
    finally:
        mock_reset()
    n429, n200 = d.get("429", 0), d.get("200", 0)
    expect(inflight_max[0] >= 16, f"the probe did not send traffic above the provider limit (max {inflight_max[0]} calls at once) — "
                                  "too few slots (ex. 06)? We check the rate limiter only with a full pool. If the previous run was "
                                  "just before, the app limiter remembers the exhausted limit (120/min) — wait a minute")
    ok = sum(1 for x in w if x["status"] == 200)
    # after ex. 12 part of the wave of 90 requests gets OUR 503 (queue full / wait budget) — that is backpressure,
    # not an effect of the provider limits; it depends on the race at the start of the wave (smoke: 0–26 of 90)
    bp = sum(1 for x in w if x["status"] == 503 and (x["json"] or {}).get("error") in ("queue_full", "slot_wait_timeout"))
    expect(n429 <= max(1, 0.01 * n200), f"the mock returned {n429}× 429 with {n200}× 200 — no rate limiter; "
                                        f"app: {statuses(w)}")
    expect(ok + bp == 90 and ok >= 45, f"app: {statuses(w)} (including rejected by backpressure: {bp})")
    return (f"90 requests: 429 at the provider = {n429}, wait p99 {pct([x['st'].get('wait') for x in w], 99):.1f} s"
            + (f", {bp} × 503 from backpressure (ex. 12)" if bp else ""))


def ex09():
    """The `overload` profile (capacity 8 + queue 8), traffic 10/s for 10 s: ≤ 1.5 HTTP attempts per request."""
    require_app()
    mock_reset()
    try:
        mock("/admin/profile/overload", "POST")
        a0 = mock_responses()
        w = traffic(claims("summary", 100), rps=10, timeout=120)
        time.sleep(1)
        d = diff(a0, mock_responses())
    finally:
        mock_reset()
    attempts = sum(v for k, v in d.items() if k.isdigit())
    r = attempts / len(w)
    expect(d.get("529", 0) > 0, f"the probe did not overload the provider (0 × 529, {statuses(w)}) — the app sends too little "
                                "at once; is the slot pool already sized (ex. 06)?")
    expect(r <= 1.5, f"{attempts} HTTP attempts for {len(w)} requests = ×{r:.2f} (529: {d.get('529', 0)}) — retries "
                     "overlap (SDK × app) and come back in a wave")
    return f"×{r:.2f} attempts per request (529: {d.get('529', 0)}, 200: {d.get('200', 0)})"


def ex10():
    """A hung provider → a fast 504 (timeout per SLO), a disconnected client → generation aborted, long calls without SDK retries."""
    require_app()
    mock_reset()
    # a) short: 60 s of silence at the provider; the app should answer 504 within the short deadline (30 s, with a fallback
    #    to `b`, which is also silent) — before the client gives up (40 s)
    t0 = time.perf_counter()
    try:
        r = httpx2.post(f"{APP}/claims/{random.randint(1, 20000)}/summary", headers={"x-mock-ttft-ms": "60000"},
                        timeout=40)
        st, dt = r.status_code, time.perf_counter() - t0
    except httpx2.TimeoutException:
        st, dt = 0, time.perf_counter() - t0
    expect(st == 504 and dt < 36, f"hung provider: status {st or 'no response'} after {dt:.0f} s — "
                                  "no read timeout / deadline for the short class")
    # b) long: the client disconnects after 3 s — the provider-side slot should come back within a few seconds
    time.sleep(1)
    g0 = mock("/admin/stats")["a"]["generating"]
    c0 = sum(v for k, v in mock_responses().items() if k.startswith("cancelled"))
    try:
        httpx2.post(f"{APP}/claims/1/analysis", headers={"x-mock-total-s": "60", "x-mock-ttft-ms": "500"}, timeout=3)
    except httpx2.TimeoutException:
        pass
    time.sleep(4)
    g1 = mock("/admin/stats")["a"]["generating"]
    c1 = sum(v for k, v in mock_responses().items() if k.startswith("cancelled"))
    expect(g1 <= g0 and c1 > c0, f"4 s after the client disconnected the mock is still generating ({g1} in flight, abandoned +{c1 - c0})"
                                 " — the app does not cancel the call")
    # c) long calls are not retried by the SDK (configuration from /diag) — at 60–300 s a retry = a cost of ×2–3
    long_client = httpx2.get(APP + "/diag", timeout=5).json()["clients"]["long"]
    expect(long_client["max_retries"] == 0, f"long client: max_retries={long_client['max_retries']} (timeout {long_client['timeout']}) — "
                                            "every timeout = another multi-minute generation")
    info = ""
    p = os.path.join(REPO, "results", "ex10-long-run.json")
    if os.path.exists(p):
        info = f"; last minute-long run: {json.load(open(p)).get('mock_delta', {}).get('a')}"
    return f"504 after {dt:.1f} s; disconnect → generation aborted; long max_retries=0{info}"


def ex11():
    """Provider `a` hung (30 s TTFT), 2/s × 40 s: the circuit breaker opens — median < 12 s, < 60% of requests to `a`."""
    require_app()
    mock_reset()
    try:
        mock("/admin/config", "PATCH", {"ttft_median_ms": 30000, "ttft_sigma": 0}, provider="a")
        a0 = mock_responses("a")
        w = traffic(claims("summary", 80), rps=2, timeout=90)
        time.sleep(1)
        delta_a = diff(a0, mock_responses("a"))
    finally:
        mock_reset()
    calls_to_a = sum(delta_a.values())
    p50 = pct([x["t"] for x in w], 50)
    expect(p50 < 12 and calls_to_a < 0.6 * len(w), f"median {p50:.1f} s, {calls_to_a}/{len(w)} went to `a` — every request "
                                                   "pays `a`'s timeout before `b` (no circuit breaker)")
    return f"median {p50:.2f} s, to `a`: {calls_to_a}/{len(w)}"


def ex12():
    """30 long calls (15 s) fill their pool; the excess long calls get a fast 503; short ones wait < 1 s."""
    require_app()

    async def run():
        limits = httpx2.Limits(max_connections=500, max_keepalive_connections=500)
        async with httpx2.AsyncClient(limits=limits) as c:
            h = {"x-mock-total-s": "15", "x-mock-ttft-ms": "500"}
            long_calls = [asyncio.create_task(_one(c, "POST", u, h, 20)) for u in claims("analysis", 30)]
            await asyncio.sleep(2.5)
            short_calls = await asyncio.gather(*(_one(c, "POST", u, {}, 20) for u in claims("summary", 20)))
            done = [d.result() for d in long_calls if d.done()]
            for d in long_calls:
                d.cancel()
            await asyncio.gather(*long_calls, return_exceptions=True)
            return short_calls, done
    short_calls, fast_rejected = asyncio.run(run())
    waits = [x["st"].get("wait") for x in short_calls if x["status"] == 200]
    n503 = sum(1 for x in fast_rejected if x["status"] == 503 and x["t"] < 0.5)
    wait_msg = f"wait p99 {pct(waits, 99):.1f} s" if waits else "none got a response within 20 s (status 0 = client timeout)"
    expect(len(waits) == 20 and pct(waits, 99) < 1.0,
           f"short calls with 30 long ones: {statuses(short_calls)}, {wait_msg} — the long calls block the shared pool")
    expect(n503 > 0, "the excess long calls did not get a fast 503 — an unbounded queue / no wait budget")
    info = ""
    p = os.path.join(REPO, "results", "ex12-mixed.json")
    if os.path.exists(p):
        k = json.load(open(p))
        info = f"; last mixed run: short wait p99 {k6_metric(k, 'app_wait_short', 'p(99)')} ms"
    return f"short wait p99 {pct(waits, 99) * 1000:.0f} ms; long calls rejected fast: {n503}{info}"


def ex13():
    """SSE stream: the first chunk reaches the client after < 30% of the whole response time."""
    require_app()

    async def run():
        async with httpx2.AsyncClient() as c:
            async def one(n):
                t0 = time.perf_counter()
                first = None
                async with c.stream("POST", f"{APP}/claims/{n}/reply/stream", timeout=60) as r:
                    async for ch in r.aiter_bytes():
                        if first is None and b"event: delta" in ch:
                            first = time.perf_counter() - t0
                return first, time.perf_counter() - t0
            return await asyncio.gather(*(one(random.randint(1, 20000)) for _ in range(5)))
    try:
        w = asyncio.run(run())
    except httpx2.TimeoutException:
        raise Fail("the stream sent nothing for 60 s (no slot or a hung provider)") from None
    expect(all(a is not None for a, _ in w), "some streams did not contain a delta event")
    r = pct([a / b for a, b in w if a], 50)
    expect(r < 0.3, f"the first chunk after {pct([a for a, _ in w], 50):.2f} s with a total of {pct([b for _, b in w], 50):.2f} s"
                    f" ({r:.0%}) — the response is buffered before sending")
    return f"client TTFT {pct([a for a, _ in w], 50):.2f} s / total {pct([b for _, b in w], 50):.2f} s"


def ex14():
    """Queue metrics (lag, age of the oldest) on :8063; 60 tasks with `overload` — 0 errors, an empty queue."""
    require_app()
    try:
        text = httpx2.get(WORKER_METRICS, timeout=5).text
    except Exception as e:  # noqa: BLE001
        raise Fail(f"no {WORKER_METRICS} ({type(e).__name__}) — run: python -m app.queue_metrics")
    for name in ("queue_lag", "queue_oldest_age_seconds"):
        expect(f"\n{name} " in "\n" + text, f"no metric {name} in {WORKER_METRICS}")
    mock_reset()
    try:
        mock("/admin/profile/overload", "POST")
        ids = [httpx2.post(f"{APP}/claims/{i}/summary/async", timeout=10).json()["task"] for i in range(1, 61)]
        states: dict = {}
        t_end = time.time() + 120
        while time.time() < t_end:
            states = {}
            for t in ids:
                s = httpx2.get(f"{APP}/jobs/{t}", timeout=10).json()["state"]
                states[s] = states.get(s, 0) + 1
            if states.get("pending_or_running", 0) == 0:
                break
            time.sleep(3)
    finally:
        mock_reset()
    expect(states.get("pending_or_running", 0) == 0, f"after 120 s: {states} — is the worker running? (taskiq worker app.tasks:broker)")
    expect(states.get("error", 0) == 0, f"tasks: {states} — worker concurrency > provider capacity (529)")
    return f"60 tasks: {states}"


def ex15():
    """50 concurrent identical FAQ questions (a new key) → exactly 1 LLM call."""
    require_app()
    q = f"does the policy cover water damage {uuid.uuid4().hex[:8]}"
    a0, b0 = mock_responses("a"), mock_responses("b")      # both: after ex. 11 traffic may go to `b` (breaker open)
    w = traffic([f"{APP}/faq?q={q}"] * 50, method="GET", timeout=60)
    n = diff(a0, mock_responses("a")).get("200", 0) + diff(b0, mock_responses("b")).get("200", 0)
    # first the number of LLM calls (the F10 symptom), statuses alongside — with other flaws (e.g. few slots → 503)
    # the status distribution alone would point to them, not to the stampede
    expect(n == 1, f"{n} LLM calls for 50 identical questions — cache stampede (no single-flight); "
                   f"responses: {statuses(w)}")
    expect(all(x["status"] == 200 for x in w), f"1 LLM call, but not everyone got a response: {statuses(w)}")
    return "50 questions → 1 LLM call"


def ex16():
    """Batch: a single request < 1.2 s (the window does not dominate), with 30 concurrent the batch is > 1 and ≤ 32."""
    require_app()
    single_times = [traffic(claims("priority", 1), timeout=30)[0]["t"] for _ in range(3)]
    w = traffic(claims("priority", 30), timeout=60)
    sizes = [x["json"]["batch_size"] for x in w if x["status"] == 200 and x["json"]]
    expect(pct(single_times, 50) < 1.2, f"a single request waits {pct(single_times, 50):.2f} s — the batch window dominates latency")
    expect(sizes and 1 < max(sizes) <= 32, f"batch sizes with 30 concurrent: max {max(sizes) if sizes else None}")
    return f"single {pct(single_times, 50):.2f} s; batch max {max(sizes)}"


def ex17():
    """The mock vs real Claude comparison saved (scripts/compare_with_claude.py)."""
    r = result_file("ex17-comparison")
    if r is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise Skip("no results/ex17-comparison.json and no ANTHROPIC_API_KEY — the exercise needs a key (cost < $0.05)")
        raise Fail("no results/ex17-comparison.json — run: python scripts/compare_with_claude.py")
    if "claude" not in r and not os.environ.get("ANTHROPIC_API_KEY"):
        raise Skip("results/ex17-comparison.json from the --mock-only mode (no claude section) — the Claude part is optional")
    expect("claude" in r and "mock" in r, "the file does not contain the claude and mock sections")
    return f"TTFT p50: claude {r['claude'].get('ttft_p50_s')} s, mock {r['mock'].get('ttft_p50_s')} s"


# Final: the incident restores these flaws; "done" = all removed (the same probes as in the exercises).
FINAL = {"F3": ex06, "F9": ex13, "F10": ex15, "F16": ex10}   # = incident.sh final (F3 as LLM_SLOTS=4)


def ex18():
    """Final: all incident flaws removed (the probes of ex. 06, 13, 15, 10)."""
    passed, failed = [], []
    for w, f in FINAL.items():
        try:
            f()
            passed.append(f"{w} ✓")
        except Fail as e:
            failed.append(f"{w}: {e}")
        except Exception as e:  # noqa: BLE001
            failed.append(f"{w}: probe error {type(e).__name__}")
    expect(not failed, " | ".join(failed))
    return ", ".join(passed)


EXERCISES = {f"{i:02d}": globals()[f"ex{i:02d}"] for i in range(1, 19)}


def main() -> int:
    args = sys.argv[1:]
    if not args or args == ["-h"] or args == ["--help"]:
        print(__doc__)
        return 0
    selected = list(EXERCISES) if "--all" in args else [a.lower().removeprefix("ex").zfill(2) for a in args]
    failed = 0
    for num in selected:
        f = EXERCISES.get(num)
        if f is None:
            print(f"?? unknown exercise {num}")
            failed += 1
            continue
        t0 = time.perf_counter()
        try:
            msg = f()
            print(f"PASS ex{num}  {msg}  [{time.perf_counter() - t0:.0f} s]", flush=True)
        except Skip as e:
            print(f"SKIP ex{num}  {e}", flush=True)
        except Fail as e:
            failed += 1
            print(f"FAIL ex{num}  {e}  [{time.perf_counter() - t0:.0f} s]", flush=True)
        except Exception as e:  # noqa: BLE001 — a probe error = a FAIL of one exercise, not the end of --all
            failed += 1
            print(f"FAIL ex{num}  probe error: {type(e).__name__}: {str(e)[:200]}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
