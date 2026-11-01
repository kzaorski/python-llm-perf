"""Telemetria aplikacji: OpenTelemetry (trace + metryki przez OTLP/HTTP) i opcjonalnie Pyroscope.

Ten moduł DZIAŁA od startu — nie jest tematem żadnego ćwiczenia. Definiuje instrumenty,
z których korzystają pozostałe moduły (nazwy w Prometheusie po konwersji OTLP w nawiasach):

- `llm.queue.wait`      [s]  czas czekania na slot LLM, atrybut `klasa`      (`llm_queue_wait_seconds_*`) — ćw. 01
- `llm.call.duration`   [s]  czas jednego wywołania LLM (bez czekania)      (`llm_call_duration_seconds_*`)
- `llm.ttft`            [s]  czas do pierwszego tokenu (ścieżki strumieniowe) (`llm_ttft_seconds_*`)
- `app.request.duration`[s]  czas end-to-end żądania (czekanie + obsługa)   (`app_request_duration_seconds_*`)
- `app.requests`             wynik żądania: ok / odrzucone / przeterminowane / anulowane / blad_dostawcy /
                             timeout_dostawcy / limit_dostawcy                (`app_requests_total`)
- `llm.http.attempts`        każda próba HTTP do dostawcy (także ponowienia SDK) (`llm_http_attempts_total`)
- `llm.http.responses`       odpowiedzi dostawcy wg statusu                   (`llm_http_responses_total`)
- `llm.waiting` / `llm.inflight` / `llm.oldest_waiting_age` — stan kolejki do LLM per klasa (gauge)
- `app.event_loop.lag`  [s]  opóźnienie pętli zdarzeń (próbkowane co 100 ms)  (`app_event_loop_lag_seconds_*`)
- `app.stream.first_chunk` [s] od wejścia żądania do wysłania klientowi PIERWSZEGO fragmentu strumienia
                             (`app_stream_first_chunk_seconds_*`) — porównaj z `llm.ttft` (ćw. 13)

Zmienne: OTEL_SERVICE_NAME (domyślnie claims-assistant), OTEL_EXPORTER_OTLP_ENDPOINT,
APP_WARIANT (etykieta wariantu uruchomienia, np. uvicorn / gunicorn-uvicorn), PYROSCOPE=1 (profilowanie),
PYROSCOPE_WALL=1 (tryb wall-clock zamiast CPU).
"""
from __future__ import annotations

import asyncio
import os
import time

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.metrics import Observation
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from . import stan

SERVICE = os.environ.get("OTEL_SERVICE_NAME", "claims-assistant")
WARIANT = os.environ.get("APP_WARIANT", "uvicorn")
os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4368")
os.environ.setdefault("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")

# Kubełki w sekundach: od milisekund (odrzucenia) po wywołania wielominutowe (do 300+ s).
KUBELKI_S = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 1, 1.5, 2, 3, 5, 7.5, 10, 15, 20, 30,
             45, 60, 90, 120, 150, 180, 240, 300, 360, 480)

_gotowe = False
tracer = trace.get_tracer("claims-assistant")
meter = metrics.get_meter("claims-assistant")


def konfiguruj(service: str | None = None, wariant: str | None = None) -> None:
    """Ustawia providery OTel (raz na proces). Wołane przy imporcie app.main i w workerze.

    `wariant` = domyślna etykieta procesu (np. worker), gdy nie ustawiono APP_WARIANT."""
    global _gotowe, tracer, meter, SERVICE, WARIANT
    if _gotowe:
        return
    if service:
        SERVICE = service
    if wariant and "APP_WARIANT" not in os.environ:
        WARIANT = wariant
    _gotowe = True
    res = Resource.create({"service.name": SERVICE, "service.instance.id": f"{WARIANT}-{os.getpid()}",
                           "app.wariant": WARIANT})
    tp = TracerProvider(resource=res)
    tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    if os.environ.get("PYROSCOPE", "0") == "1":
        _pyroscope(tp)
    trace.set_tracer_provider(tp)
    views = [View(instrument_type=None, instrument_name=n, aggregation=ExplicitBucketHistogramAggregation(KUBELKI_S))
             for n in ("llm.queue.wait", "llm.call.duration", "llm.ttft", "app.request.duration",
                       "app.event_loop.lag", "app.stream.first_chunk", "zadania.czas", "zadania.czekanie")]
    mp = MeterProvider(resource=res, views=views,
                       metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=5000)])
    metrics.set_meter_provider(mp)
    tracer = trace.get_tracer("claims-assistant")
    meter = metrics.get_meter("claims-assistant")
    _instrumenty()
    # Klient HTTP SDK anthropic 2.x stoi na httpx2 — HTTPXClientInstrumentor go NIE widzi.
    from opentelemetry.instrumentation.httpx import HTTPX2ClientInstrumentor
    HTTPX2ClientInstrumentor().instrument()


def _pyroscope(tp: TracerProvider) -> None:
    import pyroscope
    from pyroscope.otel import PyroscopeSpanProcessor
    wall = os.environ.get("PYROSCOPE_WALL", "0") == "1"
    pyroscope.configure(application_name=SERVICE,
                        server_address=os.environ.get("PYROSCOPE_URL", "http://127.0.0.1:4060"),
                        oncpu=not wall, gil_only=not wall,
                        tags={"wariant": WARIANT, "tryb": "wall" if wall else "cpu"})
    tp.add_span_processor(PyroscopeSpanProcessor())


# Instrumenty — tworzone w konfiguruj(); do tego czasu atrapy no-op (import bez skutków ubocznych).
H_CZEKANIE = H_WYWOLANIE = H_TTFT = H_ZADANIE = H_LAG = H_PIERWSZY = None
C_ZADANIA = C_PROBY = C_ODPOWIEDZI = C_CACHE = None
H_WSAD = None


def _instrumenty() -> None:
    global H_CZEKANIE, H_WYWOLANIE, H_TTFT, H_ZADANIE, H_LAG, H_PIERWSZY, C_ZADANIA, C_PROBY, C_ODPOWIEDZI, C_CACHE, H_WSAD
    H_CZEKANIE = meter.create_histogram("llm.queue.wait", unit="s", description="Czas czekania na slot LLM")
    H_WYWOLANIE = meter.create_histogram("llm.call.duration", unit="s", description="Czas wywołania LLM (obsługa)")
    H_TTFT = meter.create_histogram("llm.ttft", unit="s", description="Czas do pierwszego tokenu")
    H_ZADANIE = meter.create_histogram("app.request.duration", unit="s", description="Czas end-to-end żądania")
    H_LAG = meter.create_histogram("app.event_loop.lag", unit="s", description="Opóźnienie pętli zdarzeń")
    H_PIERWSZY = meter.create_histogram("app.stream.first_chunk", unit="s",
                                        description="Od wejścia żądania do wysłania pierwszego fragmentu strumienia")
    H_WSAD = meter.create_histogram("app.batch.size", unit="1", description="Rozmiar wsadu wysłanego do LLM")
    C_ZADANIA = meter.create_counter("app.requests", description="Żądania wg wyniku")
    C_PROBY = meter.create_counter("llm.http.attempts", description="Próby HTTP do dostawcy (z ponowieniami SDK)")
    C_ODPOWIEDZI = meter.create_counter("llm.http.responses", description="Odpowiedzi dostawcy wg statusu")
    C_CACHE = meter.create_counter("app.cache", description="Cache odpowiedzi: hit / miss / czekanie")

    def _obs(atrybut):
        def cb(_opts):
            return [Observation(atrybut(s), {"klasa": k}) for k, s in stan.STAN.items()]
        return cb

    meter.create_observable_gauge("llm.waiting", [_obs(lambda s: s.liczba_czekajacych)],
                                  description="Żądania czekające na slot LLM")
    meter.create_observable_gauge("llm.inflight", [_obs(lambda s: s.w_toku)],
                                  description="Wywołania LLM w toku")
    meter.create_observable_gauge("llm.oldest_waiting_age", [_obs(lambda s: s.wiek_najstarszego)], unit="s",
                                  description="Wiek najstarszego czekającego żądania")


def zapisz(instrument, wartosc: float, **atrybuty) -> None:
    """Bezpieczny zapis (instrument może być None, gdy telemetria nie została skonfigurowana)."""
    if instrument is None:
        return
    if hasattr(instrument, "record"):
        instrument.record(wartosc, atrybuty)
    else:
        instrument.add(wartosc, atrybuty)


async def monitor_petli(okres_s: float = 0.1) -> None:
    """Mierzy, o ile później niż zaplanowano budzi się pętla zdarzeń (blokada pętli = duży lag)."""
    while True:
        t0 = time.perf_counter()
        await asyncio.sleep(okres_s)
        lag = max(0.0, time.perf_counter() - t0 - okres_s)
        stan.PETLA.zapisz(lag)
        zapisz(H_LAG, lag)
