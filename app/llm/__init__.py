"""The LLM layer: client, limiter, deadline, retries, fallback (topics of exercises 01, 06, 08–12)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LLMJob:
    """One request to the LLM (provider-independent)."""
    request_class: str              # "short" | "long"
    endpoint: str
    prompt: str
    max_tokens: int
    system: str | None = None
    headers: dict = field(default_factory=dict)   # x-mock-* passed on to the mock


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    provider: str
    duration_s: float
    ttft_s: float | None = None
