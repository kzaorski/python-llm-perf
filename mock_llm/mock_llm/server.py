"""Atrapa LLM zgodna z Messages API Anthropic (POST /v1/messages, stream i bez).

Oficjalny SDK `anthropic` działa z nią po ustawieniu `base_url` (np. http://127.0.0.1:8061).
Modeluje to, co liczy się w testach wydajności: rozkład czasu do pierwszego tokenu (TTFT),
szybkość generowania, limity RPM/ITPM/OTPM (429 + `retry-after` + nagłówki
`anthropic-ratelimit-*`), ograniczoną moc dostawcy (kolejka po jego stronie → 529),
losowe 500/529, zerwany strumień. Konfiguracja: env `MOCK_*` + endpointy `/admin/*`.

Dostawca `a` = ścieżki bez prefiksu (oraz `/a/...`), dostawca `b` = `/b/...`
(np. `base_url="http://127.0.0.1:8061/b"`) — osobne limity i konfiguracja.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import random
import time
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from .config import PROFILES, PROVIDERS, SEED, ProviderConfig
from .words import WORDS

app = FastAPI(title="mock-llm (atrapa Messages API)", version="1.0")

M_REQ = Counter("mock_llm_requests_total", "Żądania do atrapy", ["provider", "status", "stream"])
M_TOK = Counter("mock_llm_tokens_total", "Tokeny", ["provider", "kind"])
M_INFLIGHT = Gauge("mock_llm_generating", "Generacje w toku (zajęte sloty mocy)", ["provider"])
M_WAITING = Gauge("mock_llm_provider_queue", "Żądania czekające na slot mocy dostawcy", ["provider"])
M_QWAIT = Histogram("mock_llm_provider_queue_wait_seconds", "Czas czekania w kolejce dostawcy", ["provider"],
                    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120, 300))
M_CANCEL = Counter("mock_llm_cancelled_total", "Żądania porzucone przez klienta (rozłączenie)",
                   ["provider", "phase", "stream"])
M_OLDEST = Gauge("mock_llm_oldest_inflight_seconds", "Wiek najstarszej generacji w toku", ["provider"])


class Bucket:
    """Token bucket uzupełniany ciągle (jak limity Anthropic): pojemność = limit/min."""

    def __init__(self, per_minute: int):
        self.cap = float(per_minute)
        self.level = float(per_minute)
        self.t = time.monotonic()

    def _refill(self):
        now = time.monotonic()
        if self.cap > 0:
            self.level = min(self.cap, self.level + (now - self.t) * self.cap / 60.0)
        self.t = now

    def wait_for(self, n: float) -> float:
        """Ile sekund do chwili, gdy w kubełku będzie n (0 = jest teraz)."""
        self._refill()
        if self.cap <= 0 or self.level >= n:
            return 0.0
        if n > self.cap:  # żądanie większe niż cały limit — nigdy nie przejdzie
            return 60.0
        return (n - self.level) * 60.0 / self.cap

    def take(self, n: float):
        self._refill()
        self.level -= n

    def give(self, n: float):
        self._refill()
        self.level = min(self.cap, self.level + n)

    def headers(self, name: str) -> dict:
        self._refill()
        if self.cap <= 0:
            return {}
        secs = (self.cap - self.level) * 60.0 / self.cap
        reset = datetime.fromtimestamp(time.time() + secs, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            f"anthropic-ratelimit-{name}-limit": str(int(self.cap)),
            f"anthropic-ratelimit-{name}-remaining": str(max(0, int(self.level))),
            f"anthropic-ratelimit-{name}-reset": reset,
        }


class Provider:
    def __init__(self, name: str):
        self.name = name
        self.cfg = ProviderConfig.from_env()
        self.rng = random.Random(f"{SEED}-{name}")
        self.reset_state()

    def reset_state(self):
        self.req = Bucket(self.cfg.rpm)
        self.itok = Bucket(self.cfg.itpm)
        self.otok = Bucket(self.cfg.otpm)
        self.generating = 0
        self.waiting = 0
        self.cond = asyncio.Condition()
        self.stats: dict[str, int] = {}
        self.active: dict[str, float] = {}   # msg_id -> monotonic start (generacje w toku)

    def cancelled(self, phase: str, stream: bool):
        """Klient rozłączył się: w kolejce dostawcy / przed pierwszym tokenem / w trakcie generacji."""
        key = f"cancelled_{phase}"
        self.stats[key] = self.stats.get(key, 0) + 1
        M_CANCEL.labels(self.name, phase, str(stream).lower()).inc()

    def oldest_age(self) -> float:
        return max((time.monotonic() - t for t in self.active.values()), default=0.0)

    def count(self, status: int | str, stream: bool):
        key = str(status)
        self.stats[key] = self.stats.get(key, 0) + 1
        M_REQ.labels(self.name, key, str(stream).lower()).inc()

    def limit_headers(self) -> dict:
        h = {}
        h.update(self.req.headers("requests"))
        # „tokens" = najciaśniejszy z limitów tokenowych (jak w API)
        h.update(self.itok.headers("input-tokens"))
        h.update(self.otok.headers("output-tokens"))
        tok = [b for b in (self.itok, self.otok) if b.cap > 0]
        if tok:
            tight = min(tok, key=lambda b: b.level / b.cap)
            for k, v in tight.headers("tokens").items():
                h[k] = v
        return h

    async def acquire_slot(self) -> float:
        """Czeka na slot mocy dostawcy; zwraca czas czekania [s].

        `waiting` zwiększa wywołujący (synchronicznie, przed pierwszym `await`), żeby kontrola
        przeciążenia (529) kolejnych żądań widziała kolejkę od razu; zmniejsza też wywołujący.
        """
        t0 = time.perf_counter()
        async with self.cond:
            await self.cond.wait_for(lambda: self.generating < max(1, self.cfg.capacity))
            self.generating += 1
        M_INFLIGHT.labels(self.name).set(self.generating)
        w = time.perf_counter() - t0
        M_QWAIT.labels(self.name).observe(w)
        return w

    async def release_slot(self):
        async with self.cond:
            self.generating -= 1
            M_INFLIGHT.labels(self.name).set(self.generating)
            self.cond.notify(1)


PROV: dict[str, Provider] = {p: Provider(p) for p in PROVIDERS}


# ---------------------------------------------------------------- pomocnicze

def _err(status: int, etype: str, msg: str, headers: dict | None = None) -> JSONResponse:
    h = {"request-id": "req_mock_" + uuid.uuid4().hex[:20]}
    h.update(headers or {})
    return JSONResponse({"type": "error", "error": {"type": etype, "message": msg},
                         "request_id": h["request-id"]}, status_code=status, headers=h)


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""


def count_input_tokens(body: dict) -> int:
    chars = len(_text_of(body.get("system", "")))
    for m in body.get("messages", []):
        chars += len(_text_of(m.get("content", "")))
    return max(1, math.ceil(chars / 3.5)) + 8


def _lognorm(rng: random.Random, median: float, sigma: float) -> float:
    if sigma <= 0:
        return median
    return median * math.exp(rng.gauss(0.0, sigma))


def _text_tokens(seed_bytes: bytes, n: int) -> list[str]:
    r = random.Random(hashlib.sha256(seed_bytes).digest())
    out = []
    for i in range(n):
        w = r.choice(WORDS)
        if i == 0:
            w = w.capitalize()
        out.append(w + ("." if r.random() < 0.08 else ""))
    return [w + " " for w in out]


def _validate(body: dict, cfg: ProviderConfig) -> JSONResponse | None:
    if not isinstance(body.get("model"), str) or not body["model"]:
        return _err(400, "invalid_request_error", "model: Field required")
    mt = body.get("max_tokens")
    if not isinstance(mt, int) or mt < 1:
        return _err(400, "invalid_request_error", "max_tokens: Field required (integer >= 1)")
    if not isinstance(body.get("messages"), list) or not body["messages"]:
        return _err(400, "invalid_request_error", "messages: Field required")
    if cfg.reject_sampling_params:
        for p in ("temperature", "top_p", "top_k"):
            if p in body:
                return _err(400, "invalid_request_error",
                            f"{p}: Extra inputs are not permitted for model {body['model']}")
    return None


def _provider(name: str | None) -> Provider | None:
    return PROV.get(name or "a")


# ---------------------------------------------------------------- Messages API

async def _messages(request: Request, pname: str | None):
    prov = _provider(pname)
    if prov is None:
        return _err(404, "not_found_error", f"Nieznany dostawca {pname!r}")
    cfg = prov.cfg
    try:
        body = await request.json()
    except Exception:
        return _err(400, "invalid_request_error", "Nieprawidłowy JSON")
    stream = bool(body.get("stream"))
    if cfg.require_api_key and not (request.headers.get("x-api-key") or request.headers.get("authorization")):
        prov.count(401, stream)
        return _err(401, "authentication_error", "x-api-key header is required")
    bad = _validate(body, cfg)
    if bad is not None:
        prov.count(400, stream)
        return bad

    rng = prov.rng
    # błędy losowe przed przyjęciem
    roll = rng.random()
    if roll < cfg.p_529:
        prov.count(529, stream)
        return _err(529, "overloaded_error", "Overloaded")
    if roll < cfg.p_529 + cfg.p_500:
        prov.count(500, stream)
        return _err(500, "api_error", "Internal server error")

    in_tok = count_input_tokens(body)
    max_tokens = int(body["max_tokens"])
    # limity: requests, input tokens, output tokens (szacowane z max_tokens)
    waits = {
        "requests": prov.req.wait_for(1),
        "input tokens": prov.itok.wait_for(in_tok),
        "output tokens": prov.otok.wait_for(max_tokens),
    }
    worst = max(waits, key=waits.get)
    if waits[worst] > 0:
        prov.count(429, stream)
        h = prov.limit_headers()
        h["retry-after"] = str(max(1, math.ceil(waits[worst])))
        lim = {"requests": cfg.rpm, "input tokens": cfg.itpm, "output tokens": cfg.otpm}[worst]
        return _err(429, "rate_limit_error",
                    f"This request would exceed your organization's rate limit of {lim:,} {worst} per minute. "
                    "For details, refer to: https://docs.claude.com/en/api/rate-limits.", h)
    # przeciążenie: za długa kolejka po stronie dostawcy
    if cfg.overload_queue and prov.generating >= cfg.capacity and prov.waiting >= cfg.overload_queue:
        prov.count(529, stream)
        return _err(529, "overloaded_error", "Overloaded")
    prov.req.take(1)
    prov.itok.take(in_tok)
    prov.otok.take(max_tokens)

    # długość odpowiedzi i czasy (losowane przy przyjęciu → powtarzalna sekwencja z MOCK_SEED)
    forced = request.headers.get("x-mock-output-tokens")
    if forced and forced.isdigit():
        target = int(forced)
    else:
        target = max(1, round(_lognorm(rng, cfg.out_ratio * max_tokens, cfg.out_sigma)))
    target = min(target, cfg.out_tokens_max)
    out_tok = min(target, max_tokens)
    stop_reason = "max_tokens" if target > max_tokens else "end_turn"
    ttft = _lognorm(rng, cfg.ttft_median_ms, cfg.ttft_sigma) / 1000.0
    ttft += in_tok / 1000.0 * cfg.prefill_ms_per_1k_tokens / 1000.0
    if cfg.slow_ttft_p and rng.random() < cfg.slow_ttft_p:
        ttft += cfg.slow_ttft_ms / 1000.0
    tps = max(1.0, _lognorm(rng, cfg.tokens_per_s, cfg.tokens_per_s_sigma))
    # długi ogon (wywołania wielominutowe): długi TTFT albo rozciągnięta generacja
    kind = "short"
    if cfg.long_p and rng.random() < cfg.long_p:
        kinds = [k for k, on in (("ttft", cfg.long_ttft_s_max > 0), ("gen", cfg.long_total_s_max > 0)) if on]
        if kinds:
            kind = kinds[0] if len(kinds) == 1 else rng.choice(kinds)
            if kind == "ttft":
                ttft = rng.uniform(cfg.long_ttft_s_min, cfg.long_ttft_s_max)
            else:
                tps = out_tok / max(0.001, rng.uniform(cfg.long_total_s_min, cfg.long_total_s_max))
    # nadpisanie per żądanie (testy powtarzalne, k6): x-mock-ttft-ms, x-mock-total-s
    h_ttft, h_total = request.headers.get("x-mock-ttft-ms"), request.headers.get("x-mock-total-s")
    if h_ttft:
        ttft, kind = float(h_ttft) / 1000.0, "header"
    if h_total:
        tps, kind = out_tok / max(0.001, float(h_total)), "header"
    stalls = [cfg.stall_p > 0 and rng.random() < cfg.stall_p for _ in range(0, out_tok, max(1, cfg.chunk_tokens))] \
        if stream and cfg.stall_p > 0 else []
    broken = stream and cfg.stream_error_p and rng.random() < cfg.stream_error_p
    tokens = _text_tokens(json.dumps(body, sort_keys=True).encode(), out_tok)
    msg_id = "msg_mock_" + uuid.uuid4().hex[:24]
    headers = {"request-id": "req_mock_" + uuid.uuid4().hex[:20], "x-mock-kind": kind}
    headers.update(prov.limit_headers())
    model = body["model"]
    M_TOK.labels(prov.name, "input").inc(in_tok)

    def usage(out: int) -> dict:
        return {"input_tokens": in_tok, "output_tokens": out, "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0}

    if not stream:
        got = await _acquire_or_gone(prov, request)
        if got is None:
            prov.cancelled("queue", False)
            prov.otok.give(max_tokens)
            return Response(status_code=499)
        qwait = got
        prov.active[msg_id] = time.monotonic()
        try:
            if await _sleep_or_gone(request, ttft + out_tok / tps):
                prov.cancelled("generating", False)
                return Response(status_code=499)
        except asyncio.CancelledError:
            prov.cancelled("generating", False)
            raise
        finally:
            prov.active.pop(msg_id, None)
            await prov.release_slot()
            prov.otok.give(max_tokens - out_tok)
        M_TOK.labels(prov.name, "output").inc(out_tok)
        prov.count(200, False)
        headers["x-mock-provider-queue-ms"] = f"{qwait * 1000:.1f}"
        return JSONResponse({
            "id": msg_id, "type": "message", "role": "assistant", "model": model,
            "content": [{"type": "text", "text": "".join(tokens).rstrip()}],
            "stop_reason": stop_reason, "stop_sequence": None, "usage": usage(out_tok),
        }, headers=headers)

    def sse(event: str, data: dict) -> bytes:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()

    PING = sse("ping", {"type": "ping"})
    start_events = [
        sse("message_start", {"type": "message_start", "message": {
            "id": msg_id, "type": "message", "role": "assistant", "model": model, "content": [],
            "stop_reason": None, "stop_sequence": None, "usage": usage(1)}}),
        sse("content_block_start", {"type": "content_block_start", "index": 0,
                                    "content_block": {"type": "text", "text": ""}}),
        PING,
    ]

    async def gen():
        sent = 0
        state = {"gone": False, "phase": "queue"}

        async def pause(secs: float, may_ping: bool):
            """Czeka `secs`, sprawdzając rozłączenie klienta; w trakcie ciszy wysyła `ping`."""
            end = time.monotonic() + secs
            ping = cfg.ping_interval_s if may_ping else 0.0
            next_ping = time.monotonic() + ping if ping > 0 else math.inf
            while True:
                now = time.monotonic()
                rem = end - now
                if rem <= 0:
                    return
                await asyncio.sleep(min(rem, 0.5, max(0.0, next_ping - now)))
                if secs >= 0.2 and await request.is_disconnected():
                    state["gone"] = True
                    return
                if time.monotonic() >= next_ping:
                    next_ping += ping
                    yield PING

        if await _acquire_or_gone(prov, request) is None:
            prov.cancelled("queue", True)
            prov.otok.give(max_tokens)
            return
        prov.active[msg_id] = time.monotonic()
        state["phase"] = "ttft"
        try:
            if cfg.early_start:
                for ev in start_events:
                    yield ev
            async for ev in pause(ttft, cfg.early_start):
                yield ev
            if state["gone"]:
                return
            if not cfg.early_start:
                for ev in start_events:
                    yield ev
            state["phase"] = "generating"
            step = max(1, cfg.chunk_tokens)
            for n, i in enumerate(range(0, out_tok, step)):
                part = tokens[i:i + step]
                if stalls and stalls[n]:
                    async for ev in pause(cfg.stall_ms / 1000.0, True):
                        yield ev
                if i:
                    async for ev in pause(len(part) / tps, True):
                        yield ev
                if state["gone"]:
                    return
                if broken and i >= out_tok // 2:
                    prov.count("stream_error", True)
                    yield sse("error", {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}})
                    return
                yield sse("content_block_delta", {"type": "content_block_delta", "index": 0,
                                                  "delta": {"type": "text_delta", "text": "".join(part)}})
                sent += len(part)
            yield sse("content_block_stop", {"type": "content_block_stop", "index": 0})
            yield sse("message_delta", {"type": "message_delta",
                                        "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                                        "usage": {"output_tokens": out_tok}})
            yield sse("message_stop", {"type": "message_stop"})
            prov.count(200, True)
            state["phase"] = "done"
        except (asyncio.CancelledError, OSError):
            state["gone"] = True
            raise
        finally:
            if state["gone"] and state["phase"] != "done":
                prov.cancelled(state["phase"], True)
            prov.active.pop(msg_id, None)
            await prov.release_slot()
            prov.otok.give(max_tokens - sent)
            M_TOK.labels(prov.name, "output").inc(sent)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={**headers, "cache-control": "no-cache"})


async def _sleep_or_gone(request: Request, secs: float) -> bool:
    """Śpi `secs`; co 0.5 s sprawdza rozłączenie klienta. True = klient się rozłączył."""
    end = time.monotonic() + secs
    while (rem := end - time.monotonic()) > 0:
        await asyncio.sleep(min(rem, 0.5))
        if secs >= 0.2 and await request.is_disconnected():
            return True
    return False


async def _acquire_or_gone(prov: "Provider", request: Request) -> float | None:
    """Czeka na slot mocy dostawcy, ale porzuca czekanie, gdy klient się rozłączy (None)."""
    if prov.waiting == 0 and prov.generating < max(1, prov.cfg.capacity):
        # szybka ścieżka bez `await`: slot zajęty natychmiast, więc kontrola przeciążenia
        # następnych żądań z tej samej paczki widzi go od razu
        prov.generating += 1
        M_INFLIGHT.labels(prov.name).set(prov.generating)
        M_QWAIT.labels(prov.name).observe(0.0)
        return 0.0
    prov.waiting += 1  # synchronicznie — patrz Provider.acquire_slot
    M_WAITING.labels(prov.name).set(prov.waiting)
    task = asyncio.ensure_future(prov.acquire_slot())
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=0.5)
            if done:
                return task.result()
            if await request.is_disconnected():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    return None
                await prov.release_slot()  # slot przyznany w ostatniej chwili — oddaj
                return None
    except asyncio.CancelledError:
        task.cancel()
        raise
    finally:
        prov.waiting -= 1
        M_WAITING.labels(prov.name).set(prov.waiting)


@app.post("/v1/messages")
async def messages_default(request: Request):
    return await _messages(request, None)


@app.post("/{provider}/v1/messages")
async def messages_provider(provider: str, request: Request):
    return await _messages(request, provider)


async def _count(request: Request, pname: str | None):
    body = await request.json()
    return {"input_tokens": count_input_tokens(body)}


@app.post("/v1/messages/count_tokens")
async def count_default(request: Request):
    return await _count(request, None)


@app.post("/{provider}/v1/messages/count_tokens")
async def count_provider(provider: str, request: Request):
    return await _count(request, provider)


# ---------------------------------------------------------------- admin / health / metrics

@app.get("/health")
async def health():
    return {"status": "ok", "providers": list(PROV)}


@app.get("/metrics")
async def metrics():
    for n, p in PROV.items():
        M_OLDEST.labels(n).set(p.oldest_age())
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/admin/config")
async def get_config(provider: str = "a"):
    p = _provider(provider)
    if p is None:
        return _err(404, "not_found_error", f"Nieznany dostawca {provider!r}")
    return {"provider": provider, "config": p.cfg.as_dict(), "profiles": sorted(PROFILES)}


@app.patch("/admin/config")
async def patch_config(request: Request, provider: str = "a"):
    p = _provider(provider)
    if p is None:
        return _err(404, "not_found_error", f"Nieznany dostawca {provider!r}")
    unknown = p.cfg.update(await request.json())
    if unknown:
        return _err(400, "invalid_request_error", f"Nieznane klucze: {unknown}")
    p.req, p.itok, p.otok = Bucket(p.cfg.rpm), Bucket(p.cfg.itpm), Bucket(p.cfg.otpm)
    async with p.cond:
        p.cond.notify_all()
    return {"provider": provider, "config": p.cfg.as_dict()}


@app.post("/admin/profile/{name}")
async def set_profile(name: str, provider: str = "a"):
    p = _provider(provider)
    if p is None or name not in PROFILES:
        return _err(404, "not_found_error", f"Nieznany profil/dostawca; profile: {sorted(PROFILES)}")
    p.cfg = ProviderConfig.from_env()
    p.cfg.update(PROFILES[name])
    p.req, p.itok, p.otok = Bucket(p.cfg.rpm), Bucket(p.cfg.itpm), Bucket(p.cfg.otpm)
    async with p.cond:
        p.cond.notify_all()
    return {"provider": provider, "profile": name, "config": p.cfg.as_dict()}


@app.post("/admin/reset")
async def reset(provider: str | None = None):
    names = [provider] if provider else list(PROV)
    for n in names:
        p = PROV[n]
        p.cfg = ProviderConfig.from_env()
        p.rng = random.Random(f"{SEED}-{n}")
        p.req, p.itok, p.otok = Bucket(p.cfg.rpm), Bucket(p.cfg.itpm), Bucket(p.cfg.otpm)
        p.stats = {}
    return {"reset": names}


@app.get("/admin/stats")
async def stats():
    return {n: {"responses": p.stats, "generating": p.generating, "waiting": p.waiting,
                "oldest_inflight_s": round(p.oldest_age(), 2),
                "limits": p.limit_headers()} for n, p in PROV.items()}
