"""Kolejka zadań w tle (taskiq + Redis Streams): streszczenia zlecane przez POST /claims/{n}/summary/async.

Producent (aplikacja): `await streszczenie_w_tle.kiq(n, naglowki, time.time())` → wpis w strumieniu Redis.
Worker:  taskiq worker app.zadania:broker --workers 2 --max-async-tasks 100     (domyślne wartości taskiq)
Wynik:   GET /jobs/{id} (backend wyników w Redisie, 1 h).

Ćw. 14 (W15): współbieżność workera nie wynika z niczego. Domyślnie taskiq uruchamia 2 procesy × 100
zadań naraz, a każdy proces pobiera do 100 wpisów na zapas (`xread_count`, prefetch). Dostawca ma moc
na kilka–kilkanaście generacji naraz — nadmiar dostaje 529 overloaded, zadania kończą się błędem albo
ponawiają falami, a prefetch zawłaszcza zadania w jednym procesie (drugi stoi bezczynnie).
TODO ćw. 14: dobierz --workers × --max-async-tasks do mocy/limitu dostawcy (L = λ·W) i ogranicz prefetch.
Metryki kolejki (lag, wiek najstarszego) — app/kolejka_metryki.py.
"""
from __future__ import annotations

import os
import time

from taskiq import TaskiqEvents, TaskiqState
from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker

from . import config, dane, telemetry
from .llm import Zadanie, klient, ponowienia

STRUMIEN = "llmperf:zadania"
GRUPA = "llmperf-worker"
PREFETCH = int(os.environ.get("ZADANIA_PREFETCH", "100"))   # W15: domyślne xread_count taskiq-redis

broker = RedisStreamBroker(config.REDIS_URL, queue_name=STRUMIEN, consumer_group_name=GRUPA,
                           xread_count=PREFETCH).with_result_backend(
    RedisAsyncResultBackend(config.REDIS_URL, result_ex_time=3600))

_C_WYKONANE = _H_CZAS = _H_CZEKANIE = None


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def _start(state: TaskiqState) -> None:
    global _C_WYKONANE, _H_CZAS, _H_CZEKANIE
    telemetry.konfiguruj(service="claims-worker", wariant="worker")
    _C_WYKONANE = telemetry.meter.create_counter("zadania.wykonane", description="Zadania wg wyniku")
    _H_CZAS = telemetry.meter.create_histogram("zadania.czas", unit="s", description="Czas wykonania zadania")
    _H_CZEKANIE = telemetry.meter.create_histogram("zadania.czekanie", unit="s",
                                                   description="Czas od zlecenia do startu zadania")


@broker.task(task_name="streszczenie_w_tle")
async def streszczenie_w_tle(n: int, naglowki: dict, zlecono: float) -> dict:
    start = time.time()
    telemetry.zapisz(_H_CZEKANIE, max(0.0, start - zlecono))
    z = Zadanie(klasa="krotkie", endpoint="summary-job", max_tokens=200, naglowki=naglowki,
                prompt=f"Streść zgłoszenie dla likwidatora w 3 zdaniach.\n{dane.opis_dla_llm(dane.zgloszenie(n))}")
    wynik = "ok"
    try:
        w = await ponowienia.z_ponowieniami(lambda: klient.zapytaj(z))
        return {"zgloszenie": dane.zgloszenie(n)["id"], "streszczenie": w.tekst,
                "czekanie_s": round(start - zlecono, 3), "czas_s": round(time.time() - start, 3)}
    except Exception as e:
        wynik = type(e).__name__
        raise
    finally:
        telemetry.zapisz(_C_WYKONANE, 1, wynik=wynik)
        telemetry.zapisz(_H_CZAS, time.time() - start)
