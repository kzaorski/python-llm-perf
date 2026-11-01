#!/usr/bin/env python3
"""check.py — maszynowe sprawdzenie kryteriów „done" ćwiczeń kursu python-llm-perf.

    python check.py 06          # jedno ćwiczenie
    python check.py --all       # wszystkie (regresja kursu)
    python check.py 04 06 09    # kilka

Sprawdzamy ZACHOWANIE działającej aplikacji (port 8060), a nie kod: krótkie sondy obciążeniowe (sekundy),
API atrapy LLM (/admin/stats), Tempo (trace po znanym trace-id), metryki kolejki (8063) i pliki
podsumowań k6 w wyniki/. Testów wielominutowych check nie uruchamia — ćw. 10 i 12 mają sondy
skrócone (nagłówki x-mock-*), a wyniki Twoich przebiegów minutowych czyta z wyniki/, jeśli są.
Sondy zmieniające konfigurację atrapy przywracają ją na koniec (POST /admin/reset).

Zmienne: APP_URL (http://127.0.0.1:8060), MOCK_URL (http://127.0.0.1:8061), GUNICORN_URL (…:8062),
GRAFANA_URL (http://127.0.0.1:3060), WORKER_METRICS_URL (http://127.0.0.1:8063/metrics),
CHECK_LOOKBACK_H (24) — jak stare pliki wyniki/*.json uznajemy.
Kod wyjścia: 0 = wszystko PASS/SKIP, 1 = co najmniej jeden FAIL.
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


def oczekuj(warunek: bool, opis: str) -> None:
    if not warunek:
        raise Fail(opis)


# ---------------------------------------------------------------- narzędzia
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


def mock(path: str, metoda="GET", body=None, provider=None) -> dict:
    r = httpx2.request(metoda, MOCK + path, json=body, params={"provider": provider} if provider else None, timeout=5)
    r.raise_for_status()
    return r.json()


def mock_odp(p="a") -> dict:
    return mock("/admin/stats")[p]["responses"]


def roznica(a: dict, b: dict) -> dict:
    return {k: b.get(k, 0) - a.get(k, 0) for k in set(a) | set(b) if b.get(k, 0) != a.get(k, 0)}


def mock_reset() -> None:
    try:
        mock("/admin/reset", "POST")
    except Exception:  # noqa: BLE001
        pass


async def _jedno(c, metoda, url, headers, timeout):
    t0 = time.perf_counter()
    try:
        r = await c.request(metoda, url, headers=headers, timeout=timeout)
        try:
            body = r.json()
        except Exception:  # noqa: BLE001
            body = None
        return {"status": r.status_code, "t": time.perf_counter() - t0,
                "st": server_timing(r.headers.get("server-timing")), "json": body}
    except Exception as e:  # noqa: BLE001
        return {"status": 0, "t": time.perf_counter() - t0, "st": {}, "json": None, "err": type(e).__name__}


async def _ruch(urle, metoda="POST", headers=None, timeout=60.0, rps=None):
    """Wysyła żądania naraz (rps=None) albo w modelu otwartym (rps żądań/s, niezależnie od odpowiedzi)."""
    limity = httpx2.Limits(max_connections=5000, max_keepalive_connections=5000)
    async with httpx2.AsyncClient(limits=limity) as c:
        zad = []
        t0 = time.perf_counter()
        for i, u in enumerate(urle):
            zad.append(asyncio.create_task(_jedno(c, metoda, u, headers or {}, timeout)))
            if rps:
                await asyncio.sleep(max(0.0, t0 + (i + 1) / rps - time.perf_counter()))
        return await asyncio.gather(*zad)


def ruch(urle, **kw):
    return asyncio.run(_ruch(urle, **kw))


def claims(sciezka: str, n: int, start: int | None = None) -> list[str]:
    s = start if start is not None else random.randint(1, 15000)
    return [f"{APP}/claims/{s + i}/{sciezka}" for i in range(n)]


def statusy(w) -> dict:
    out: dict = {}
    for x in w:
        out[x["status"]] = out.get(x["status"], 0) + 1
    return out


def plik_wyniku(nazwa: str) -> dict | None:
    p = os.path.join(REPO, "wyniki", f"{nazwa}.json")
    if not os.path.exists(p) or time.time() - os.path.getmtime(p) > LOOKBACK_H * 3600:
        return None
    with open(p) as f:
        return json.load(f)


def metryka_k6(dane: dict, nazwa: str, stat: str):
    return ((dane.get("metrics") or {}).get(nazwa) or {}).get("values", {}).get(stat)


def wymagaj_aplikacji(drain_s: float = 45.0) -> None:
    """Aplikacja odpowiada i nie ma zaległości z poprzednich sond (inaczej pomiar byłby niewiarygodny)."""
    try:
        httpx2.get(APP + "/diag/ping", timeout=5).raise_for_status()
    except Exception as e:  # noqa: BLE001
        raise Fail(f"aplikacja nie odpowiada na {APP} ({type(e).__name__}) — uruchom: uvicorn app.main:app --port 8060")
    t_end = time.time() + drain_s
    while True:
        try:
            k = httpx2.get(APP + "/diag", timeout=5).json()["kolejka"]
        except Exception:  # noqa: BLE001 — starsza wersja /diag: nie sprawdzamy zaległości
            return
        zajete = sum(v["czekajace"] + v["w_toku"] for v in k.values())
        if zajete == 0:
            return
        if time.time() > t_end:
            raise Fail(f"aplikacja ma zaległość z wcześniejszego ruchu ({k}) — praca trwa mimo rozłączonych klientów "
                       "(brak anulowania, ćw. 10?); zrestartuj aplikację i powtórz")
        time.sleep(2)


# ---------------------------------------------------------------- ćwiczenia
def ex01():
    """Trace żądania pokazuje czas czekania na slot: span llm.queue_wait + atrybut llm.queue.wait_ms."""
    wymagaj_aplikacji()
    trace_id = uuid.uuid4().hex
    tp = f"00-{trace_id}-{uuid.uuid4().hex[:16]}-01"
    r = httpx2.post(f"{APP}/claims/{random.randint(1, 20000)}/summary", headers={"traceparent": tp}, timeout=60)
    oczekuj(r.status_code == 200, f"POST /summary → {r.status_code}")
    spany: list = []
    for _ in range(12):                      # eksport co ~5 s + ingest Tempo
        time.sleep(2.5)
        t = httpx2.get(f"{GRAFANA}/api/datasources/proxy/uid/tempo/api/traces/{trace_id}", auth=AUTH, timeout=10)
        if t.status_code == 200:
            spany = [s for b in t.json().get("batches", t.json().get("resourceSpans", []))
                     for ss in b.get("scopeSpans", b.get("instrumentationLibrarySpans", [])) for s in ss.get("spans", [])]
            if any(s["name"] == "llm.call" for s in spany):
                break
    nazwy = sorted({s["name"] for s in spany})
    oczekuj(spany, f"trace {trace_id} nie dotarł do Tempo w 30 s (czy app wysyła OTLP na :4368?)")
    oczekuj("llm.queue_wait" in nazwy, f"brak spanu llm.queue_wait w trace (są: {nazwy})")
    attrs = {a["key"] for s in spany for a in s.get("attributes", [])}
    oczekuj("llm.queue.wait_ms" in attrs, "brak atrybutu llm.queue.wait_ms na spanie żądania")
    czek = next(s for s in spany if s["name"] == "llm.queue_wait")
    rodzic_call = next((s.get("parentSpanId") for s in spany if s["name"] == "llm.call"), None)
    oczekuj(rodzic_call != czek.get("spanId"), "llm.call jest dzieckiem llm.queue_wait — czekanie ma być RODZEŃSTWEM")
    return f"trace {trace_id[:8]}…: spany {nazwy}"


def ex02():
    """Oba przebiegi k6 (model zamknięty i otwarty) w wyniki/, p99 otwartego > zamkniętego, 0 zgubionych iteracji."""
    z, o = plik_wyniku("ex02-zamkniety"), plik_wyniku("ex02-otwarty")
    oczekuj(z is not None, "brak wyniki/ex02-zamkniety.json — uruchom k6/zamkniety.js")
    oczekuj(o is not None, "brak wyniki/ex02-otwarty.json — uruchom k6/otwarty.js (najpierw uzupełnij scenariusz)")
    pz, po = metryka_k6(z, "http_req_duration", "p(99)"), metryka_k6(o, "http_req_duration", "p(99)")
    drop = metryka_k6(o, "dropped_iterations", "count") or 0
    oczekuj(pz and po, "brak http_req_duration p(99) w podsumowaniach")
    oczekuj(drop == 0, f"model otwarty zgubił {drop} iteracji (dropped_iterations) — za mało VU")
    oczekuj(po > 1.3 * pz, f"p99 otwarty {po / 1000:.2f} s nie jest wyraźnie > zamknięty {pz / 1000:.2f} s — "
                           "czy oba przebiegi miały tę samą nominalną intensywność blisko pojemności?")
    return f"p99 zamknięty {pz / 1000:.2f} s, otwarty {po / 1000:.2f} s, dropped=0"


def ex03():
    """Przebieg rampy (k6/rampa.js) zapisany: osiągnięte tempo i czasy po schodkach."""
    r = plik_wyniku("ex03-rampa")
    oczekuj(r is not None, "brak wyniki/ex03-rampa.json — uruchom k6/rampa.js")
    n = metryka_k6(r, "http_reqs", "count") or 0
    oczekuj(n >= 200, f"rampa ma tylko {n} żądań — puść pełną rampę")
    return f"rampa: {n} żądań, p99 {metryka_k6(r, 'http_req_duration', 'p(99)') / 1000:.2f} s"


def ex04():
    """Ruch otwarty 6/s na /classify przez 10 s: proces nadąża, a /diag/ping odpowiada od razu (pętla wolna)."""
    wymagaj_aplikacji()

    async def run():
        pingi: list = []
        stop = asyncio.Event()

        async def pinguj():
            async with httpx2.AsyncClient() as c:
                while not stop.is_set():
                    t0 = time.perf_counter()
                    try:
                        await c.get(APP + "/diag/ping", timeout=30)
                    except Exception:  # noqa: BLE001
                        pass
                    pingi.append(time.perf_counter() - t0)
                    await asyncio.sleep(0.1)
        tp = asyncio.create_task(pinguj())
        t0 = time.perf_counter()
        w = await _ruch(claims("classify", 60), rps=6, timeout=60)
        total = time.perf_counter() - t0
        stop.set()
        await tp
        return w, total, pingi
    w, total, pingi = asyncio.run(run())
    ok = sum(1 for x in w if x["status"] == 200)
    p99 = pct([x["t"] for x in w], 99)
    oczekuj(pct(pingi, 99) < 0.25, f"/diag/ping p99 {pct(pingi, 99):.2f} s (max {max(pingi):.1f} s) — pętla zdarzeń "
                                   f"zablokowana; /classify p99 {p99:.1f} s, ostatnia odpowiedź po {total:.0f} s")
    oczekuj(ok == len(w) and total < 15, f"/classify: {ok}/{len(w)} OK, ostatnia po {total:.0f} s (dopływ 10 s)")
    return f"/classify 6/s: p99 {p99:.2f} s, ostatnia po {total:.1f} s; /diag/ping p99 {pct(pingi, 99) * 1000:.0f} ms"


def ex05():
    """60 równoległych /letter (każde ~2.1 s u atrapy) kończy się jedną falą — bez czekania na wątek z puli (40)."""
    wymagaj_aplikacji()
    h = {"x-mock-ttft-ms": "2000", "x-mock-total-s": "0.1"}
    w = ruch(claims("letter", 60), headers=h, timeout=60)
    ts = [x["t"] for x in w if x["status"] == 200]
    oczekuj(len(ts) == 60, f"tylko {len(ts)}/60 odpowiedzi 200: {statusy(w)}")
    druga = sum(1 for t in ts if t > 1.5 * min(ts))
    oczekuj(max(ts) < 1.5 * min(ts), f"{druga} z 60 żądań czekało na drugą „falę\" (min {min(ts):.2f} s, max {max(ts):.2f} s)"
                                     " — handler zajmuje wątek puli anyio")
    return f"60× /letter: min {min(ts):.2f} s, max {max(ts):.2f} s (jedna fala)"


def ex06():
    """Ruch otwarty 20/s na /summary przez 10 s: czekanie na slot p99 < 0.5 s (pula dobrana do λ·W)."""
    wymagaj_aplikacji()
    w = ruch(claims("summary", 200), rps=20, timeout=120)
    cz = [x["st"].get("czekanie") for x in w if x["status"] == 200]
    llm = [x["st"].get("llm") for x in w if x["status"] == 200]
    oczekuj(len(cz) >= 190, f"tylko {len(cz)}/200 odpowiedzi 200: {statusy(w)}")
    oczekuj(pct(cz, 99) < 0.5, f"czekanie na slot p50 {pct(cz, 50):.1f} s / p99 {pct(cz, 99):.1f} s przy obsłudze "
                               f"LLM p50 {pct(llm, 50):.2f} s — za mało slotów (L = λ·W)")
    return f"20/s: czekanie p99 {pct(cz, 99) * 1000:.0f} ms, LLM p50 {pct(llm, 50):.2f} s"


def ex07():
    """Na :8062 działa gunicorn z UvicornWorker (aplikacja ASGI), 40 równoległych żądań w jednej fali."""
    try:
        h = httpx2.get(GUNICORN + "/health", timeout=5).json()
    except Exception as e:  # noqa: BLE001
        raise Fail(f"nic nie odpowiada na {GUNICORN} ({type(e).__name__}) — uruchom: gunicorn -c gunicorn.conf.py")
    oczekuj(h.get("serwer") == "gunicorn-uvicorn", f"/health na 8062 zgłasza serwer={h.get('serwer')!r} "
                                                   "(oczekiwany gunicorn-uvicorn: UvicornWorker + app.main)")
    hdr = {"x-mock-ttft-ms": "2000", "x-mock-total-s": "0.1"}
    s = random.randint(1, 15000)
    w = ruch([f"{GUNICORN}/claims/{s + i}/summary" for i in range(40)], headers=hdr, timeout=60)
    ts = [x["t"] for x in w if x["status"] == 200]
    oczekuj(len(ts) == 40, f"{len(ts)}/40 odpowiedzi 200: {statusy(w)}")
    oczekuj(max(ts) < 3.5, f"40 żądań po ~2.1 s: max {max(ts):.1f} s — żądania czekają na wolny worker")
    return f"gunicorn-uvicorn: 40× max {max(ts):.2f} s"


def ex08():
    """Profil `limity`: 90 żądań naraz → atrapa nie zwraca 429 (limiter po naszej stronie), wszystkie 200."""
    wymagaj_aplikacji()
    mock_reset()
    try:
        mock("/admin/profile/limity", "POST")
        a0 = mock_odp()
        w_toku_max = [0]

        async def probkuj_i_wyslij():
            async def probkuj():
                async with httpx2.AsyncClient() as c:
                    while True:
                        try:
                            k = (await c.get(APP + "/diag", timeout=5)).json()["kolejka"]["krotkie"]
                            w_toku_max[0] = max(w_toku_max[0], k["w_toku"])
                        except Exception:  # noqa: BLE001
                            pass
                        await asyncio.sleep(0.3)
            tp = asyncio.create_task(probkuj())
            r = await _ruch(claims("summary", 90), timeout=180)
            tp.cancel()
            return r
        w = asyncio.run(probkuj_i_wyslij())
        d = roznica(a0, mock_odp())
    finally:
        mock_reset()
    n429, n200 = d.get("429", 0), d.get("200", 0)
    oczekuj(w_toku_max[0] >= 16, f"sonda nie wysłała ruchu ponad limit dostawcy (max {w_toku_max[0]} wywołań naraz) — "
                                 "za mało slotów (ćw. 06)? Limiter tempa sprawdzamy dopiero przy pełnej puli")
    ok = sum(1 for x in w if x["status"] == 200)
    oczekuj(n429 <= max(1, 0.01 * n200), f"atrapa zwróciła {n429}× 429 przy {n200}× 200 — brak limitera tempa; "
                                         f"aplikacja: {statusy(w)}")
    oczekuj(ok == 90, f"aplikacja: {statusy(w)}")
    return f"90 żądań: 429 u dostawcy = {n429}, czekanie p99 {pct([x['st'].get('czekanie') for x in w], 99):.1f} s"


def ex09():
    """Profil `przeciazenie` (moc 8 + kolejka 8), ruch 10/s przez 10 s: ≤ 1.5 próby HTTP na żądanie."""
    wymagaj_aplikacji()
    mock_reset()
    try:
        mock("/admin/profile/przeciazenie", "POST")
        a0 = mock_odp()
        w = ruch(claims("summary", 100), rps=10, timeout=120)
        time.sleep(1)
        d = roznica(a0, mock_odp())
    finally:
        mock_reset()
    proby = sum(v for k, v in d.items() if k.isdigit())
    r = proby / len(w)
    oczekuj(d.get("529", 0) > 0, f"sonda nie przeciążyła dostawcy (0 × 529, {statusy(w)}) — aplikacja wysyła za mało "
                                 "naraz; czy pula slotów jest już dobrana (ćw. 06)?")
    oczekuj(r <= 1.5, f"{proby} prób HTTP na {len(w)} żądań = ×{r:.2f} (529: {d.get('529', 0)}) — ponowienia "
                      "nakładają się (SDK × aplikacja) i wracają falą")
    return f"×{r:.2f} prób na żądanie (529: {d.get('529', 0)}, 200: {d.get('200', 0)})"


def ex10():
    """Zawieszony dostawca → szybkie 504 (timeout wg SLO), rozłączony klient → generacja przerwana, długie bez ponowień SDK."""
    wymagaj_aplikacji()
    mock_reset()
    # a) krótkie: 60 s ciszy u dostawcy; aplikacja ma odpowiedzieć 504 zanim klient zrezygnuje (25 s)
    t0 = time.perf_counter()
    try:
        r = httpx2.post(f"{APP}/claims/{random.randint(1, 20000)}/summary", headers={"x-mock-ttft-ms": "60000"},
                        timeout=25)
        st, dt = r.status_code, time.perf_counter() - t0
    except httpx2.TimeoutException:
        st, dt = 0, time.perf_counter() - t0
    oczekuj(st == 504 and dt < 32, f"zawieszony dostawca: status {st or 'brak odpowiedzi'} po {dt:.0f} s — "
                                   "brak timeoutu odczytu / deadline'u dla krótkich")
    # b) długie: klient rozłącza się po 3 s — slot u dostawcy ma wrócić w ciągu kilku sekund
    time.sleep(1)
    g0 = mock("/admin/stats")["a"]["generating"]
    c0 = sum(v for k, v in mock_odp().items() if k.startswith("cancelled"))
    try:
        httpx2.post(f"{APP}/claims/1/analysis", headers={"x-mock-total-s": "60", "x-mock-ttft-ms": "500"}, timeout=3)
    except httpx2.TimeoutException:
        pass
    time.sleep(4)
    g1 = mock("/admin/stats")["a"]["generating"]
    c1 = sum(v for k, v in mock_odp().items() if k.startswith("cancelled"))
    oczekuj(g1 <= g0 and c1 > c0, f"4 s po rozłączeniu klienta atrapa wciąż generuje ({g1} w toku, porzuconych +{c1 - c0})"
                                  " — aplikacja nie anuluje wywołania")
    # c) długie nie są ponawiane przez SDK (konfiguracja z /diag) — przy 60–300 s ponowienie = koszt ×2–3
    kl = httpx2.get(APP + "/diag", timeout=5).json()["klienci"]["dlugie"]
    oczekuj(kl["max_retries"] == 0, f"klient długich: max_retries={kl['max_retries']} (timeout {kl['timeout']}) — "
                                    "każdy timeout = kolejna wielominutowa generacja")
    info = ""
    p = os.path.join(REPO, "wyniki", "ex10-dlugie-przebieg.json")
    if os.path.exists(p):
        info = f"; ostatni przebieg minutowy: {json.load(open(p)).get('atrapa_przyrost', {}).get('a')}"
    return f"504 po {dt:.1f} s; rozłączenie → generacja przerwana; długie max_retries=0{info}"


def ex11():
    """Dostawca `a` zawieszony (30 s TTFT): wyłącznik otwiera się, mediana < 5 s, do `a` trafia < 50% żądań."""
    wymagaj_aplikacji()
    mock_reset()
    try:
        mock("/admin/config", "PATCH", {"ttft_median_ms": 30000, "ttft_sigma": 0}, provider="a")
        a0 = mock_odp("a")
        w = ruch(claims("summary", 40), rps=2, timeout=90)
        time.sleep(1)
        da = roznica(a0, mock_odp("a"))
    finally:
        mock_reset()
    do_a = sum(da.values())
    p50 = pct([x["t"] for x in w], 50)
    oczekuj(p50 < 5 and do_a < 0.5 * len(w), f"mediana {p50:.1f} s, do `a` poszło {do_a}/{len(w)} — każde żądanie "
                                             "płaci timeout `a` przed `b` (brak wyłącznika)")
    return f"mediana {p50:.2f} s, do `a`: {do_a}/{len(w)}"


def ex12():
    """30 długich (15 s) zajmuje swoją pulę; nadmiar długich dostaje szybkie 503; krótkie czekają < 1 s."""
    wymagaj_aplikacji()

    async def run():
        limity = httpx2.Limits(max_connections=500, max_keepalive_connections=500)
        async with httpx2.AsyncClient(limits=limity) as c:
            h = {"x-mock-total-s": "15", "x-mock-ttft-ms": "500"}
            dlugie = [asyncio.create_task(_jedno(c, "POST", u, h, 20)) for u in claims("analysis", 30)]
            await asyncio.sleep(2.5)
            krotkie = await asyncio.gather(*(_jedno(c, "POST", u, {}, 20) for u in claims("summary", 20)))
            gotowe = [d.result() for d in dlugie if d.done()]
            for d in dlugie:
                d.cancel()
            await asyncio.gather(*dlugie, return_exceptions=True)
            return krotkie, gotowe
    krotkie, odrzucone_szybko = asyncio.run(run())
    cz = [x["st"].get("czekanie") for x in krotkie if x["status"] == 200]
    n503 = sum(1 for x in odrzucone_szybko if x["status"] == 503 and x["t"] < 0.5)
    oczekuj(len(cz) == 20 and pct(cz, 99) < 1.0,
            f"krótkie przy 30 długich: {statusy(krotkie)}, czekanie p99 {pct(cz, 99):.1f} s — długie blokują wspólną pulę")
    oczekuj(n503 > 0, "nadmiar długich nie dostał szybkiego 503 — kolejka bez limitu / bez budżetu czekania")
    info = ""
    p = os.path.join(REPO, "wyniki", "ex12-mieszany.json")
    if os.path.exists(p):
        k = json.load(open(p))
        info = f"; ostatni przebieg mieszany: czekanie krótkich p99 {metryka_k6(k, 'app_czekanie_krotkie', 'p(99)')} ms"
    return f"krótkie czekanie p99 {pct(cz, 99) * 1000:.0f} ms; długich odrzuconych szybko: {n503}{info}"


def ex13():
    """Strumień SSE: pierwszy fragment u klienta po < 30% czasu całej odpowiedzi."""
    wymagaj_aplikacji()

    async def run():
        async with httpx2.AsyncClient() as c:
            async def jedno(n):
                t0 = time.perf_counter()
                pierwszy = None
                async with c.stream("POST", f"{APP}/claims/{n}/reply/stream", timeout=60) as r:
                    async for ch in r.aiter_bytes():
                        if pierwszy is None and b"event: delta" in ch:
                            pierwszy = time.perf_counter() - t0
                return pierwszy, time.perf_counter() - t0
            return await asyncio.gather(*(jedno(random.randint(1, 20000)) for _ in range(5)))
    try:
        w = asyncio.run(run())
    except httpx2.TimeoutException:
        raise Fail("strumień nie wysłał nic przez 60 s (brak slotu albo zawieszony dostawca)") from None
    oczekuj(all(a is not None for a, _ in w), "część strumieni nie zawierała zdarzenia delta")
    r = pct([a / b for a, b in w if a], 50)
    oczekuj(r < 0.3, f"pierwszy fragment po {pct([a for a, _ in w], 50):.2f} s przy całości {pct([b for _, b in w], 50):.2f} s"
                     f" ({r:.0%}) — odpowiedź buforowana przed wysłaniem")
    return f"TTFT klienta {pct([a for a, _ in w], 50):.2f} s / całość {pct([b for _, b in w], 50):.2f} s"


def ex14():
    """Metryki kolejki (lag, wiek najstarszego) w :8063; 60 zadań przy `przeciazenie` — 0 błędów, kolejka pusta."""
    wymagaj_aplikacji()
    try:
        tekst = httpx2.get(WORKER_METRICS, timeout=5).text
    except Exception as e:  # noqa: BLE001
        raise Fail(f"brak {WORKER_METRICS} ({type(e).__name__}) — uruchom: python -m app.kolejka_metryki")
    for nazwa in ("kolejka_lag", "kolejka_wiek_najstarszego_s"):
        oczekuj(f"\n{nazwa} " in "\n" + tekst, f"brak metryki {nazwa} w {WORKER_METRICS}")
    mock_reset()
    try:
        mock("/admin/profile/przeciazenie", "POST")
        ids = [httpx2.post(f"{APP}/claims/{i}/summary/async", timeout=10).json()["zadanie"] for i in range(1, 61)]
        stany: dict = {}
        t_end = time.time() + 120
        while time.time() < t_end:
            stany = {}
            for t in ids:
                s = httpx2.get(f"{APP}/jobs/{t}", timeout=10).json()["stan"]
                stany[s] = stany.get(s, 0) + 1
            if stany.get("czeka_lub_w_toku", 0) == 0:
                break
            time.sleep(3)
    finally:
        mock_reset()
    oczekuj(stany.get("czeka_lub_w_toku", 0) == 0, f"po 120 s: {stany} — czy worker działa? (taskiq worker app.zadania:broker)")
    oczekuj(stany.get("blad", 0) == 0, f"zadania: {stany} — współbieżność workera > moc dostawcy (529)")
    return f"60 zadań: {stany}"


def ex15():
    """50 równoczesnych identycznych pytań FAQ (nowy klucz) → dokładnie 1 wywołanie LLM."""
    wymagaj_aplikacji()
    q = f"czy polisa obejmuje szkody od zalania {uuid.uuid4().hex[:8]}"
    a0 = mock_odp()
    w = ruch([f"{APP}/faq?q={q}"] * 50, metoda="GET", timeout=60)
    n = roznica(a0, mock_odp()).get("200", 0)
    oczekuj(all(x["status"] == 200 for x in w), f"odpowiedzi: {statusy(w)}")
    oczekuj(n == 1, f"{n} wywołań LLM dla 50 identycznych pytań — cache stampede (brak single-flight)")
    return "50 pytań → 1 wywołanie LLM"


def ex16():
    """Wsad: pojedyncza prośba < 1.2 s (okno nie dominuje), przy 30 równoległych wsad > 1 i ≤ 32."""
    wymagaj_aplikacji()
    poj = [ruch(claims("priority", 1), timeout=30)[0]["t"] for _ in range(3)]
    w = ruch(claims("priority", 30), timeout=60)
    rozm = [x["json"]["rozmiar_wsadu"] for x in w if x["status"] == 200 and x["json"]]
    oczekuj(pct(poj, 50) < 1.2, f"pojedyncza prośba czeka {pct(poj, 50):.2f} s — okno wsadu dominuje latencję")
    oczekuj(rozm and 1 < max(rozm) <= 32, f"rozmiary wsadów przy 30 równoległych: max {max(rozm) if rozm else None}")
    return f"pojedyncza {pct(poj, 50):.2f} s; wsad max {max(rozm)}"


def ex17():
    """Porównanie atrapy z prawdziwym Claude zapisane (scripts/porownaj_z_claude.py)."""
    r = plik_wyniku("ex17-porownanie")
    if r is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise Skip("brak wyniki/ex17-porownanie.json i ANTHROPIC_API_KEY — ćwiczenie wymaga klucza (koszt < $0.05)")
        raise Fail("brak wyniki/ex17-porownanie.json — uruchom: python scripts/porownaj_z_claude.py")
    oczekuj("claude" in r and "atrapa" in r, "plik nie zawiera sekcji claude i atrapa")
    return f"TTFT p50: claude {r['claude'].get('ttft_p50_s')} s, atrapa {r['atrapa'].get('ttft_p50_s')} s"


# Finał: incydent przywraca te wady; „done" = wszystkie usunięte (te same sondy co w ćwiczeniach).
FINAL = {"W3": ex06, "W9": ex13, "W10": ex15, "W16": ex10}   # = incydent.sh final (W3 jako LLM_SLOTY=4)


def ex18():
    """Finał: wszystkie wady incydentu usunięte (sondy ćw. 06, 13, 15, 10)."""
    wyn, zle = [], []
    for w, f in FINAL.items():
        try:
            f()
            wyn.append(f"{w} ✓")
        except Fail as e:
            zle.append(f"{w}: {e}")
        except Exception as e:  # noqa: BLE001
            zle.append(f"{w}: błąd sondy {type(e).__name__}")
    oczekuj(not zle, " | ".join(zle))
    return ", ".join(wyn)


CWICZENIA = {f"{i:02d}": globals()[f"ex{i:02d}"] for i in range(1, 19)}


def main() -> int:
    args = sys.argv[1:]
    if not args or args == ["-h"] or args == ["--help"]:
        print(__doc__)
        return 0
    wybrane = list(CWICZENIA) if "--all" in args else [a.zfill(2) for a in args]
    zle = 0
    for nr in wybrane:
        f = CWICZENIA.get(nr)
        if f is None:
            print(f"?? nieznane ćwiczenie {nr}")
            zle += 1
            continue
        t0 = time.perf_counter()
        try:
            msg = f()
            print(f"PASS ex{nr}  {msg}  [{time.perf_counter() - t0:.0f} s]", flush=True)
        except Skip as e:
            print(f"SKIP ex{nr}  {e}", flush=True)
        except Fail as e:
            zle += 1
            print(f"FAIL ex{nr}  {e}  [{time.perf_counter() - t0:.0f} s]", flush=True)
        except Exception as e:  # noqa: BLE001 — błąd sondy = FAIL jednego ćwiczenia, nie koniec --all
            zle += 1
            print(f"FAIL ex{nr}  błąd sondy: {type(e).__name__}: {str(e)[:200]}", flush=True)
    return 1 if zle else 0


if __name__ == "__main__":
    sys.exit(main())
