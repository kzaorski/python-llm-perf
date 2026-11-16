"""Telemetry for the app: OpenTelemetry (traces + metrics over OTLP/HTTP) and, optionally, Pyroscope.

This module WORKS from startup — it is not a topic of any exercise. It defines the instruments
that the other modules use (Prometheus names after OTLP conversion in parentheses):

- `llm.queue.wait`      [s]  time waiting for an LLM slot, attribute `request_class`  (`llm_queue_wait_seconds_*`) — ex. 01
- `llm.call.duration`   [s]  time of one LLM call (without waiting)                   (`llm_call_duration_seconds_*`)
- `llm.ttft`            [s]  time to first token (streaming paths)                    (`llm_ttft_seconds_*`)
- `app.request.duration`[s]  end-to-end request time (waiting + service)              (`app_request_duration_seconds_*`)
- `app.requests`             request outcome: ok / rejected / deadline_exceeded / cancelled / provider_error /
                             provider_timeout / provider_rate_limited                 (`app_requests_total`)
- `llm.http.attempts`        every HTTP attempt to the provider (including SDK retries) (`llm_http_attempts_total`)
- `llm.http.responses`       provider responses by status                             (`llm_http_responses_total`)
- `llm.waiting` / `llm.inflight` / `llm.oldest_waiting_age` — state of the LLM queue per class (gauge)
- `app.event_loop.lag`  [s]  event loop delay (sampled every 100 ms)                  (`app_event_loop_lag_seconds_*`)
- `app.stream.first_chunk` [s] from the request entering to the FIRST stream chunk being sent to the client
                             (`app_stream_first_chunk_seconds_*`) — compare with `llm.ttft` (ex. 13)

Variables: OTEL_SERVICE_NAME (default claims-assistant), OTEL_EXPORTER_OTLP_ENDPOINT,
APP_VARIANT (label of the run variant, e.g. uvicorn / gunicorn-uvicorn), PYROSCOPE=1 (profiling),
PYROSCOPE_WALL=1 (wall-clock mode instead of CPU).
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

from . import state

SERVICE = os.environ.get("OTEL_SERVICE_NAME", "claims-assistant")
VARIANT = os.environ.get("APP_VARIANT", "uvicorn")
os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4368")
os.environ.setdefault("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")

# Buckets in seconds: from milliseconds (rejections) to multi-minute calls (300+ s).
BUCKETS_S = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 1, 1.5, 2, 3, 5, 7.5, 10, 15, 20, 30,
             45, 60, 90, 120, 150, 180, 240, 300, 360, 480)

_ready = False
tracer = trace.get_tracer("claims-assistant")
meter = metrics.get_meter("claims-assistant")


def configure(service: str | None = None, variant: str | None = None) -> None:
    """Sets up the OTel providers (once per process). Called on import of app.main and in the worker.

    `variant` = the default process label (e.g. worker) when APP_VARIANT is not set."""
    global _ready, tracer, meter, SERVICE, VARIANT
    if _ready:
        return
    if service:
        SERVICE = service
    if variant and "APP_VARIANT" not in os.environ:
        VARIANT = variant
    _ready = True
    res = Resource.create({"service.name": SERVICE, "service.instance.id": f"{VARIANT}-{os.getpid()}",
                           "app.variant": VARIANT})
    tp = TracerProvider(resource=res)
    tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    if os.environ.get("PYROSCOPE", "0") == "1":
        _pyroscope(tp)
    trace.set_tracer_provider(tp)
    views = [View(instrument_type=None, instrument_name=n, aggregation=ExplicitBucketHistogramAggregation(BUCKETS_S))
             for n in ("llm.queue.wait", "llm.call.duration", "llm.ttft", "app.request.duration",
                       "app.event_loop.lag", "app.stream.first_chunk", "tasks.duration", "tasks.wait")]
    mp = MeterProvider(resource=res, views=views,
                       metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=5000)])
    metrics.set_meter_provider(mp)
    tracer = trace.get_tracer("claims-assistant")
    meter = metrics.get_meter("claims-assistant")
    _instruments()
    # The HTTP client of the anthropic 2.x SDK is built on httpx2 — HTTPXClientInstrumentor does NOT see it.
    from opentelemetry.instrumentation.httpx import HTTPX2ClientInstrumentor
    HTTPX2ClientInstrumentor().instrument()


def _pyroscope(tp: TracerProvider) -> None:
    import pyroscope
    from pyroscope.otel import PyroscopeSpanProcessor
    wall = os.environ.get("PYROSCOPE_WALL", "0") == "1"
    pyroscope.configure(application_name=SERVICE,
                        server_address=os.environ.get("PYROSCOPE_URL", "http://127.0.0.1:4060"),
                        oncpu=not wall, gil_only=not wall,
                        tags={"variant": VARIANT, "mode": "wall" if wall else "cpu"})
    tp.add_span_processor(PyroscopeSpanProcessor())


# Instruments — created in configure(); until then no-op placeholders (importing has no side effects).
H_QUEUE_WAIT = H_CALL = H_TTFT = H_REQUEST = H_LAG = H_FIRST_CHUNK = None
C_REQUESTS = C_ATTEMPTS = C_RESPONSES = C_CACHE = None
H_BATCH = None


def _instruments() -> None:
    global H_QUEUE_WAIT, H_CALL, H_TTFT, H_REQUEST, H_LAG, H_FIRST_CHUNK, C_REQUESTS, C_ATTEMPTS, C_RESPONSES, C_CACHE, H_BATCH
    H_QUEUE_WAIT = meter.create_histogram("llm.queue.wait", unit="s", description="Time waiting for an LLM slot")
    H_CALL = meter.create_histogram("llm.call.duration", unit="s", description="LLM call time (service)")
    H_TTFT = meter.create_histogram("llm.ttft", unit="s", description="Time to first token")
    H_REQUEST = meter.create_histogram("app.request.duration", unit="s", description="End-to-end request time")
    H_LAG = meter.create_histogram("app.event_loop.lag", unit="s", description="Event loop delay")
    H_FIRST_CHUNK = meter.create_histogram("app.stream.first_chunk", unit="s",
                                           description="From the request entering to the first stream chunk being sent")
    H_BATCH = meter.create_histogram("app.batch.size", unit="1", description="Size of the batch sent to the LLM")
    C_REQUESTS = meter.create_counter("app.requests", description="Requests by outcome")
    C_ATTEMPTS = meter.create_counter("llm.http.attempts", description="HTTP attempts to the provider (with SDK retries)")
    C_RESPONSES = meter.create_counter("llm.http.responses", description="Provider responses by status")
    C_CACHE = meter.create_counter("app.cache", description="Response cache: hit / miss / shared")

    def _obs(attribute):
        def cb(_opts):
            return [Observation(attribute(s), {"request_class": k}) for k, s in state.STATE.items()]
        return cb

    meter.create_observable_gauge("llm.waiting", [_obs(lambda s: s.waiting_count)],
                                  description="Requests waiting for an LLM slot")
    meter.create_observable_gauge("llm.inflight", [_obs(lambda s: s.inflight)],
                                  description="LLM calls in flight")
    meter.create_observable_gauge("llm.oldest_waiting_age", [_obs(lambda s: s.oldest_age)], unit="s",
                                  description="Age of the oldest waiting request")


def record(instrument, value: float, **attributes) -> None:
    """Safe recording (the instrument may be None when telemetry has not been configured)."""
    if instrument is None:
        return
    if hasattr(instrument, "record"):
        instrument.record(value, attributes)
    else:
        instrument.add(value, attributes)


async def monitor_loop(period_s: float = 0.1) -> None:
    """Measures how much later than scheduled the event loop wakes up (loop blocking = large lag)."""
    while True:
        t0 = time.perf_counter()
        await asyncio.sleep(period_s)
        lag = max(0.0, time.perf_counter() - t0 - period_s)
        state.LOOP_LAG.record(lag)
        record(H_LAG, lag)
