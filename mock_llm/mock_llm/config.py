"""Mock LLM configuration: defaults from env (MOCK_*), changed at runtime through /admin.

Each "provider" (`a` — the default, `b` — the fallback for the fallback exercises) has its own
configuration, its own limit buckets and its own compute capacity pool.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, fields


def _env(name: str, default, cast):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    if cast is bool:
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return cast(raw)


@dataclass
class ProviderConfig:
    # --- delays ---
    ttft_median_ms: float = 450.0       # median time to first token (log-normal distribution)
    ttft_sigma: float = 0.35            # sigma of the log-normal TTFT (0 = a constant value)
    prefill_ms_per_1k_tokens: float = 40.0  # extra TTFT ms per 1000 input tokens
    tokens_per_s: float = 250.0         # median generation speed (tokens/s)
    tokens_per_s_sigma: float = 0.15
    slow_ttft_p: float = 0.0            # probability of a "slow first token"
    slow_ttft_ms: float = 3000.0        # how many ms a slow first token adds
    chunk_tokens: int = 3               # tokens per content_block_delta event
    # --- response length ---
    out_ratio: float = 0.7              # median response length as a fraction of max_tokens
    out_sigma: float = 0.25
    out_tokens_max: int = 4000
    # --- provider limits (a token bucket, refilled continuously; 0 = no limit) ---
    rpm: int = 4000                     # requests per minute
    itpm: int = 2000000                 # input tokens per minute
    otpm: int = 400000                     # output tokens per minute (estimated from max_tokens at the start)
    # --- provider compute capacity ---
    capacity: int = 64                  # how many generations at once; the excess waits in the provider's queue
    overload_queue: int = 256           # more than this many waiting → 529 overloaded_error (0 = no limit)
    # --- random errors ---
    p_529: float = 0.0                  # probability of a 529 overloaded_error on entry
    p_500: float = 0.0                  # probability of a 500 api_error on entry
    stream_error_p: float = 0.0         # probability of an `error` event in the middle of a stream
    # --- multi-minute calls (the tail of long responses; 0 = off) ---
    long_p: float = 0.0                 # the share of requests from the "long tail" (drawn from MOCK_SEED)
    long_ttft_s_min: float = 0.0        # long TTFT: silence before the first token, U[min,max] s
    long_ttft_s_max: float = 0.0
    long_total_s_min: float = 0.0       # long generation: the total generation time U[min,max] s
    long_total_s_max: float = 0.0       #   (the token rate is chosen to hit this time)
    stall_p: float = 0.0                # probability of a pause before a stream chunk
    stall_ms: float = 0.0               # the length of a pause between chunks
    early_start: bool = False           # stream: message_start right after accepting, silence afterwards
    ping_interval_s: float = 0.0        # stream: `ping` events every N s during the silence (0 = none)
    # --- API compatibility ---
    reject_sampling_params: bool = True  # 5.x models: temperature/top_p/top_k → 400
    require_api_key: bool = True

    @classmethod
    def from_env(cls, prefix: str = "MOCK_") -> "ProviderConfig":
        kw = {}
        for f in fields(cls):
            kw[f.name] = _env(prefix + f.name.upper(), f.default, type(f.default))
        return cls(**kw)

    def update(self, data: dict) -> list[str]:
        """A partial update (PATCH). Returns the list of unknown keys."""
        unknown = []
        types = {f.name: type(f.default) for f in fields(self)}
        for k, v in data.items():
            if k not in types:
                unknown.append(k)
                continue
            t = types[k]
            setattr(self, k, (str(v).lower() in ("1", "true", "yes", "on")) if t is bool and not isinstance(v, bool) else t(v))
        return unknown

    def as_dict(self) -> dict:
        return asdict(self)


# Named profiles: quick switching of scenarios in the exercises (POST /admin/profile/<name>).
PROFILES: dict[str, dict] = {
    "default": {},
    # limits like on a low account tier: easy to hit a 429 from one machine
    "limits": {"rpm": 120, "itpm": 60000, "otpm": 12000},
    # a provider with little capacity: 8 generations at once, a queue of 8, above that — 529 overloaded
    "overload": {"capacity": 8, "overload_queue": 8},
    # every fifth call with a very slow first token
    "slow-start": {"slow_ttft_p": 0.2, "slow_ttft_ms": 3000},
    # an unstable provider: random 529/500 and broken streams
    "unstable": {"p_529": 0.05, "p_500": 0.02, "stream_error_p": 0.03},
    # --- minute-long profiles (requirement: calls of 60–300 s) ---
    # every call: 60–180 s of silence before the first token, then the usual rate
    "long-ttft": {"long_p": 1.0, "long_ttft_s_min": 60, "long_ttft_s_max": 180},
    # a short TTFT, but the generation stretched to 120–300 s (stream or non-stream)
    "long-stream": {"long_p": 1.0, "long_total_s_min": 120, "long_total_s_max": 300},
    # mixed traffic: 80% short, 20% a 60–300 s tail (half of the tail = a long TTFT)
    "mixed": {"long_p": 0.2, "long_ttft_s_min": 60, "long_ttft_s_max": 180,
              "long_total_s_min": 60, "long_total_s_max": 240},
    # a stream with pauses: ~2% of chunks are preceded by 20 s of silence (a read/idle timeout test)
    "pauses": {"long_p": 1.0, "long_total_s_min": 60, "long_total_s_max": 120,
               "stall_p": 0.02, "stall_ms": 20000},
    # like long-ttft, but headers and message_start right away + a ping every 15 s (keep-alive)
    "long-ttft-ping": {"long_p": 1.0, "long_ttft_s_min": 60, "long_ttft_s_max": 180,
                       "early_start": True, "ping_interval_s": 15},
}

SEED = _env("MOCK_SEED", 20261031, int)
PROVIDERS = ("a", "b")
