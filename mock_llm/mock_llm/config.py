"""Konfiguracja atrapy LLM: wartości domyślne z env (MOCK_*), zmiana w locie przez /admin.

Każdy „dostawca" (`a` — domyślny, `b` — zapasowy do ćwiczeń z fallbackiem) ma własną
konfigurację, własne kubełki limitów i własną pulę mocy obliczeniowej.
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
    # --- opóźnienia ---
    ttft_median_ms: float = 450.0       # mediana czasu do pierwszego tokenu (rozkład log-normalny)
    ttft_sigma: float = 0.35            # sigma log-normalnego TTFT (0 = stała wartość)
    prefill_ms_per_1k_tokens: float = 40.0  # dodatkowe ms TTFT na każde 1000 tokenów wejścia
    tokens_per_s: float = 250.0         # mediana szybkości generowania (tokeny/s)
    tokens_per_s_sigma: float = 0.15
    slow_ttft_p: float = 0.0            # prawdopodobieństwo „wolnego pierwszego tokenu"
    slow_ttft_ms: float = 3000.0        # ile ms dokłada wolny pierwszy token
    chunk_tokens: int = 3               # tokenów na jedno zdarzenie content_block_delta
    # --- długość odpowiedzi ---
    out_ratio: float = 0.7              # mediana długości odpowiedzi jako ułamek max_tokens
    out_sigma: float = 0.25
    out_tokens_max: int = 4000
    # --- limity dostawcy (token bucket, uzupełniany ciągle; 0 = bez limitu) ---
    rpm: int = 4000                     # żądania na minutę
    itpm: int = 2000000                 # tokeny wejścia na minutę
    otpm: int = 400000                     # tokeny wyjścia na minutę (szacowane z max_tokens na starcie)
    # --- moc obliczeniowa dostawcy ---
    capacity: int = 64                  # ile generacji naraz; nadmiar czeka w kolejce dostawcy
    overload_queue: int = 256           # >tyle czekających → 529 overloaded_error (0 = bez limitu)
    # --- błędy losowe ---
    p_529: float = 0.0                  # prawdopodobieństwo 529 overloaded_error na wejściu
    p_500: float = 0.0                  # prawdopodobieństwo 500 api_error na wejściu
    stream_error_p: float = 0.0         # prawdopodobieństwo zdarzenia `error` w połowie strumienia
    # --- zgodność z API ---
    reject_sampling_params: bool = True  # modele 5.x: temperature/top_p/top_k → 400
    require_api_key: bool = True

    @classmethod
    def from_env(cls, prefix: str = "MOCK_") -> "ProviderConfig":
        kw = {}
        for f in fields(cls):
            kw[f.name] = _env(prefix + f.name.upper(), f.default, type(f.default))
        return cls(**kw)

    def update(self, data: dict) -> list[str]:
        """Częściowa aktualizacja (PATCH). Zwraca listę nieznanych kluczy."""
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


# Profile nazwane: szybkie przełączanie scenariuszy w ćwiczeniach (POST /admin/profile/<nazwa>).
PROFILES: dict[str, dict] = {
    "domyslny": {},
    # limity jak na niskim progu konta: łatwo dobić 429 z jednej maszyny
    "limity": {"rpm": 120, "itpm": 60000, "otpm": 12000},
    # dostawca z małą mocą: kolejka po stronie dostawcy, potem 529
    "przeciazenie": {"capacity": 8, "overload_queue": 32},
    # co piąte wywołanie z bardzo wolnym pierwszym tokenem
    "wolny-start": {"slow_ttft_p": 0.2, "slow_ttft_ms": 3000},
    # niestabilny dostawca: losowe 529/500 i zerwane strumienie
    "niestabilny": {"p_529": 0.05, "p_500": 0.02, "stream_error_p": 0.03},
}

SEED = _env("MOCK_SEED", 20261031, int)
PROVIDERS = ("a", "b")
