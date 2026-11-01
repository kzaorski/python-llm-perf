"""Konfiguracja aplikacji z env (wartości domyślne = .env.example)."""
import os


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


APP_PORT = _int("APP_PORT", 8060)
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8061")
LLM_FALLBACK_BASE_URL = os.environ.get("LLM_FALLBACK_BASE_URL", "http://127.0.0.1:8061/b")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "mock-key")
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-haiku-5-5")
REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6460/0")
DATA_PATH = os.environ.get("CLAIMS_DATA", os.path.join(os.path.dirname(__file__), "..", "data", "zgloszenia.jsonl"))
# Zapasowy dostawca (ćw. 11): 1 = przy awarii dostawcy `a` próbuj `b`.
LLM_FALLBACK = os.environ.get("LLM_FALLBACK", "1") == "1"
# Nagłówki sterujące atrapą, które aplikacja przekazuje dalej (powtarzalne testy z k6).
# Prawdziwe API ich nie zna; przy dostawcy innym niż atrapa ustaw MOCK_HEADERS=0.
MOCK_HEADERS = os.environ.get("MOCK_HEADERS", "1") == "1"
NAGLOWKI_ATRAPY = ("x-mock-ttft-ms", "x-mock-total-s", "x-mock-output-tokens")
