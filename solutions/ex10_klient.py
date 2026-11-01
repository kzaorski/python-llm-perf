"""[ROZWIĄZANIE ćw. 10 (zawiera 09) — kopiuj do app/llm/klient.py] Klienci LLM (AsyncAnthropic) per klasa żądań i per dostawca.

Ćw. 09 — ponowienia: ile prób wykonuje SDK (`max_retries`) POD ponowieniami aplikacji (W5).
Ćw. 10 — timeouty: czym jest `timeout` SDK (connect/read/write/pool — limity PER OPERACJA,
          read = bezczynność), a czym deadline całkowity (app/llm/wywolanie.py) (W6, W17).

Obecny stan (celowe wady, zmierzone w Bloku B):
- klient krótkich: ✅ ćw. 09 `max_retries=0`; ✅ ćw. 10 timeouty wg SLO (read 15 s);
- klient długich: ✅ ćw. 10 strumień, read 60 s = bezczynność, `max_retries=0`.
"""
from __future__ import annotations

import os
import time

import anthropic
import httpx2

from .. import config, stan, telemetry
from . import Wynik, Zadanie, limiter

ADRESY = {"a": config.LLM_BASE_URL, "b": config.LLM_FALLBACK_BASE_URL}
# Rozmiar puli połączeń httpx2 na dostawcę (0 = domyślna SDK: 1000). Ćw. 06 — wariant „pula < semafor".
POLACZENIA = int(os.environ.get("LLM_POLACZENIA", "0"))


# ---------------------------------------------------------------- infrastruktura pomiaru (nie zmieniaj)
def _http(dostawca: str, **kw):
    """Klient httpx2 SDK z hakami liczącymi KAŻDĄ próbę HTTP (także ponowienia wewnątrz SDK)."""

    async def przy_zadaniu(request):
        telemetry.zapisz(telemetry.C_PROBY, 1, dostawca=dostawca)

    async def przy_odpowiedzi(response):
        stan.PROBY_HTTP[(dostawca, response.status_code)] += 1
        telemetry.zapisz(telemetry.C_ODPOWIEDZI, 1, dostawca=dostawca, status=str(response.status_code))
        if dostawca == "a":
            limiter.aktualizuj_z_naglowkow(response.status_code, response.headers)

    if POLACZENIA:     # ćw. 06: pula połączeń httpx2 mniejsza niż semafor → czekanie w puli / PoolTimeout
        kw["limits"] = httpx2.Limits(max_connections=POLACZENIA, max_keepalive_connections=POLACZENIA)
    return anthropic.DefaultAsyncHttpxClient(event_hooks={"request": [przy_zadaniu], "response": [przy_odpowiedzi]},
                                             **kw)


def _nowy(dostawca: str, **kw) -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(base_url=ADRESY[dostawca], api_key=config.LLM_API_KEY,
                                    http_client=_http(dostawca), **kw)


# ---------------------------------------------------------------- konfiguracja klientów (ćw. 09, 10)
# ćw. 09 (W5): JEDNA warstwa ponowień — w aplikacji (app/llm/ponowienia.py: backoff + jitter + budżet).
#   SDK nie ponawia (max_retries=0), więc jedna prośba = co najwyżej 1 + 2 próby, a nie 3 × 3.
# ćw. 10 (W6): timeouty krótkich wg ich SLO, nie „na zapas". Bez strumienia read = czas aż do całej
#   odpowiedzi; streszczenie u atrapy p99 ≈ 2 s, prawdziwy Claude ~1–4 s, więc 15 s ciszy to awaria
#   dostawcy, nie ogon rozkładu. connect 3 s (lokalna sieć/TLS), pool 5 s. Całość pilnuje deadline
#   w app/llm/wywolanie.py (krótkie: 30 s) — read NIE jest limitem całkowitym.
TIMEOUT_KROTKIE = anthropic.Timeout(connect=3.0, read=15.0, write=10.0, pool=5.0)
KROTKIE = {d: _nowy(d, max_retries=0, timeout=TIMEOUT_KROTKIE) for d in ADRESY}
# ćw. 10 (W17): długie (60–300 s) idą STRUMIENIEM. Wtedy read timeout to limit BEZCZYNNOŚCI między
#   zdarzeniami (tokeny albo `ping` co ~15 s od dostawcy), a nie czas całej odpowiedzi — 60 s ciszy
#   to awaria. Bez ponowień w SDK: powtórka 4-minutowej generacji po timeoucie to podwójny koszt
#   i drugie tyle czekania; o ponowieniu decyduje aplikacja (deadline 330 s w wywolanie.py).
TIMEOUT_DLUGIE = anthropic.Timeout(connect=3.0, read=60.0, write=10.0, pool=5.0)
DLUGIE = {d: _nowy(d, max_retries=0, timeout=TIMEOUT_DLUGIE) for d in ADRESY}


def klient(klasa: str, dostawca: str) -> anthropic.AsyncAnthropic:
    return (DLUGIE if klasa == "dlugie" else KROTKIE)[dostawca]


async def zapytaj(z: Zadanie, dostawca: str = "a") -> Wynik:
    """Jedno wywołanie Messages API u wskazanego dostawcy (długie — strumieniem, ćw. 10)."""
    if z.klasa == "dlugie":
        return await _zapytaj_strumieniem(z, dostawca)
    k = klient(z.klasa, dostawca)
    t0 = time.perf_counter()
    kw = {"system": z.system} if z.system else {}
    m = await k.messages.create(model=config.LLM_MODEL, max_tokens=z.max_tokens,
                                messages=[{"role": "user", "content": z.prompt}],
                                extra_headers=z.naglowki or None, **kw)
    tekst = "".join(b.text for b in m.content if getattr(b, "type", "") == "text")
    return Wynik(tekst, m.usage.input_tokens, m.usage.output_tokens, dostawca, time.perf_counter() - t0)


async def strumien(z: Zadanie, dostawca: str = "a"):
    """Strumień fragmentów tekstu (async generator) — używany przez app/strumien.py (ćw. 13)."""
    k = klient(z.klasa, dostawca)
    kw = {"system": z.system} if z.system else {}
    async with k.messages.stream(model=config.LLM_MODEL, max_tokens=z.max_tokens,
                                 messages=[{"role": "user", "content": z.prompt}],
                                 extra_headers=z.naglowki or None, **kw) as s:
        async for tekst in s.text_stream:
            yield tekst


async def _zapytaj_strumieniem(z: Zadanie, dostawca: str) -> Wynik:
    """ćw. 10: wywołanie wielominutowe przez strumień — read timeout = bezczynność, mierzymy TTFT.

    Uwaga: timeout W TRAKCIE strumienia to surowy httpx2.ReadTimeout (nie anthropic.APITimeoutError).
    """
    k = klient(z.klasa, dostawca)
    t0 = time.perf_counter()
    ttft = None
    czesci = []
    kw = {"system": z.system} if z.system else {}
    async with k.messages.stream(model=config.LLM_MODEL, max_tokens=z.max_tokens,
                                 messages=[{"role": "user", "content": z.prompt}],
                                 extra_headers=z.naglowki or None, **kw) as s:
        async for tekst in s.text_stream:
            if ttft is None:
                ttft = time.perf_counter() - t0
            czesci.append(tekst)
        m = await s.get_final_message()
    return Wynik("".join(czesci), m.usage.input_tokens, m.usage.output_tokens, dostawca,
                 time.perf_counter() - t0, ttft)
