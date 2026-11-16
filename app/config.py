"""App configuration from env (defaults = .env.example)."""
import os


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


APP_PORT = _int("APP_PORT", 8060)
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8061")
LLM_FALLBACK_BASE_URL = os.environ.get("LLM_FALLBACK_BASE_URL", "http://127.0.0.1:8061/b")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "mock-key")
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-haiku-5-5")
REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6460/0")
DATA_PATH = os.environ.get("CLAIMS_DATA", os.path.join(os.path.dirname(__file__), "..", "data", "claims.jsonl"))
# Fallback provider (ex. 11): 1 = when provider `a` fails, try `b`.
LLM_FALLBACK = os.environ.get("LLM_FALLBACK", "1") == "1"
# Mock control headers that the app passes on (repeatable tests with k6).
# The real API does not know them; with a provider other than the mock set MOCK_HEADERS=0.
MOCK_HEADERS = os.environ.get("MOCK_HEADERS", "1") == "1"
MOCK_HEADER_NAMES = ("x-mock-ttft-ms", "x-mock-total-s", "x-mock-output-tokens")
