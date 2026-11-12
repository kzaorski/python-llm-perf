# Kurs python-llm-perf — aplikacja Pythona z LLM pod obciążeniem

Praktyczny kurs „learn-by-doing” o wydajności aplikacji, które większość czasu **czekają**: na odpowiedź
modelu językowego, na slot, na limit dostawcy, w kolejce. Pracujesz na asystencie biura obsługi zgłoszeń
szkodowych (FastAPI + asyncio + SDK Anthropic), obciążasz go k6 i obserwujesz w Grafanie (Tempo, Prometheus,
Pyroscope). Aplikacja startuje z wszytymi wadami — ich znalezienie, zmierzenie i naprawa to treść 18 ćwiczeń.
Instrukcje po polsku.

> Kurs zweryfikowany 2026-11 na: Python 3.13.13, fastapi 0.162.0, starlette 1.10.0, uvicorn 0.54.0,
> gunicorn 26.2.0 + uvicorn-worker 0.4.0, anthropic 2.3.0 (httpx2 2.16.0), opentelemetry-sdk 1.45.2
> (instrumentacje 0.66b2), pyroscope-io 1.4.0, taskiq 0.13.0 + taskiq-redis 1.2.4, redis-py 8.1.0,
> obrazy `grafana/otel-lgtm:0.39.0`, `grafana/k6:2.3.0`, `redis:8.8.4-alpine`, atrapa LLM 1.1 (`python:3.13.18-slim-trixie`).
> Smoke od zera (2026-11-01, świeży klon, Docker Desktop na macOS, arm64): świeża instalacja na Pythonie **3.11.17**
> (najniższa obsługiwana) i 3.13.13; pierwszy `docker compose up -d --wait` na pustych wolumenach ~10 s (obrazy
> w cache, bez pobierania), `pip install` + dane ~20 s; ćw. 01 i 12 (przebiegi 180 s A i B) wykonane dosłownie —
> liczby zgodne z tabelami; `check.py --all` na szkielecie: 17 × FAIL + SKIP ex17 (bez wyjątków, ~11 min);
> `./smoke.sh` na rozwiązaniach: 17 × PASS + SKIP ex17 (bez klucza), ~7 min.

Nacisk na teorię i jasne tłumaczenie pojęć — zacznij od `exercises/00-teoria.md`, przed blokami czytaj
`exercises/NNa-*.md`, definicje w `slownik.md` (hasła z odnośnikami do ćwiczeń).

## Wymagania wstępne

- **Musisz umieć:** Python (asyncio na poziomie `async`/`await`), podstawy HTTP, uruchamianie testów
  obciążeniowych (dowolne narzędzie), Docker i terminal.
- **Nie musisz umieć** (kurs uczy od podstaw): teorii kolejek i prawa Little'a, modelu otwartego vs zamkniętego
  w testach, wnętrza asyncio (pętla, pule wątków), OpenTelemetry/TraceQL/PromQL, k6, taskiq.
- **Sprzęt:** Docker (Docker Desktop na macOS działa), ~4 GB RAM dla kontenerów, Python 3.11–3.14
  (repo wskazuje 3.13 w `.python-version`).
- **Konto LLM nie jest potrzebne.** Cały kurs działa na lokalnej atrapie zgodnej z Messages API. Klucz
  Anthropic przydaje się tylko w opcjonalnym ćw. 17 (koszt ≈ $0.005).

## Architektura

```
  k6 (kontener, profil tools) ──HTTP──▶  aplikacja FastAPI  (lokalnie, :8060; wariant gunicorn :8062)
       model otwarty / zamknięty          │  semafory/pule per klasa, limiter tempa, ponowienia,
                                          │  deadline + anulowanie, wyłącznik, backpressure, cache, wsady
                                          ├──Messages API──▶ atrapa LLM  (kontener mock-llm, :8061)
                                          │                  dostawca „a” i „b”, limity, 429/529, SSE,
                                          │                  profile minutowe (60–300 s), /admin/*
                                          ├──Redis Streams──▶ worker taskiq (lokalnie) + eksporter metryk :8063
                                          ├──Redis :6460 (cache FAQ, kolejka zadań, wyniki)
                                          └──OTLP/HTTP :4368, Pyroscope :4060──▶ grafana/otel-lgtm
                                                 Grafana :3060 (Tempo, Prometheus :9196, Pyroscope)
```

Aplikacja, gunicorn i worker działają **lokalnie** — edytujesz kod i restartujesz proces bez przebudowy
obrazu. k6 dociera do hosta przez `host.docker.internal`.

## Szybki start

0. Własny branch na pracę: `git switch -c moje-cwiczenia` — ćwiczenia modyfikują pliki aplikacji; czysty
   `main` to darmowy reset, a `git diff main` pokaże na końcu wszystko, co zbudowałeś/aś.
1. Zbuduj lokalny obraz atrapy LLM i uruchom stos (z katalogu głównego repozytorium):
   ```bash
   docker compose build mock-llm
   docker compose up -d --wait
   ```
   Obraz `llmperf-mock-llm:1.1` jest budowany z katalogu `mock_llm/` — nie jest opublikowany
   na Docker Hubie. Na nowym komputerze najpierw wykonaj krok budowania; pominięcie go może
   spowodować komunikat `pull access denied for llmperf-mock-llm`. Powtórz budowanie po zmianach
   w kodzie atrapy lub jej Dockerfile.
   Stos (projekt `llmperf`): `lgtm`, `redis`, `mock-llm` →
   Grafana http://127.0.0.1:3060 (admin/admin).
2. Środowisko: `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
   (albo `uv venv && uv pip install -r requirements.txt`).
3. Zmienne (opcjonalnie — domyślne wartości są w kodzie): `cp .env.example .env; set -a; source .env; set +a`.
4. Dane: `python scripts/generuj_zgloszenia.py` (20 000 zgłoszeń → `data/`).
5. Aplikacja: `uvicorn app.main:app --port 8060`; sprawdzenie: `curl -s 127.0.0.1:8060/health`.
6. Zacznij od `exercises/00-teoria.md`, potem `EXERCISES.md` → `exercises/01-pierwszy-trace.md`.

## Uruchamianie i narzędzia

| Co | Polecenie |
|---|---|
| aplikacja (szkielet z wadami) | `uvicorn app.main:app --port 8060` |
| wariant gunicorn (ćw. 07) | `gunicorn -c gunicorn.conf.py` (:8062) |
| worker kolejki + metryki (ćw. 14) | `taskiq worker app.zadania:broker --workers 2 --max-async-tasks 4` i `python -m app.kolejka_metryki` (:8063) |
| ruch k6 | `docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/<plik>.js -e ZMIENNA=…` → podsumowanie w `wyniki/` |
| przebieg z próbkowaniem zaległości | `python scripts/pomiar.py <nazwa> --dopływ-s 180 -- run …` → `wyniki/<nazwa>-przebieg.json` (zaległość na koniec dopływu, drain) |
| TTFT strumienia u klienta | `python scripts/strumien_ttft.py -n 20 -c 5` |
| stan aplikacji „po ćw. NN” | `python scripts/nakladka.py --do NN` → `uvicorn --app-dir .run/do-NN app.main:app --port 8060` |
| atrapa LLM | `curl -s 127.0.0.1:8061/admin/stats`, `POST /admin/profile/<nazwa>`, `PATCH /admin/config?provider=a`, `POST /admin/reset` |
| stan aplikacji | `curl -s 127.0.0.1:8060/diag` (kolejka per klasa, lag pętli, wyniki, próby HTTP, timeouty klientów) |
| kryteria „done” | `python check.py exNN` / `python check.py --all` |
| mini-incydenty i finał | `./incydent.sh start mini-I|mini-II|mini-III|mini-IV|final`, `./incydent.sh ruch`, `./incydent.sh stop` |
| regresja na rozwiązaniach | `./smoke.sh` (~7 min, wymaga wolnych 8060/8062/8063) |

Utknąłeś? Najpierw stopniowane podpowiedzi w `solutions/hints/` (kierunek → API/metryka → pseudokod), dopiero
potem gotowe wersje w `solutions/` (patrz `solutions/README.md`).

## Mapa repo

| Ścieżka | Co to |
|---|---|
| `app/` | aplikacja FastAPI; `app/llm/` — klient, limiter (sloty, tempo), ponowienia, deadline/anulowanie, fallback |
| `mock_llm/` | atrapa LLM (obraz `llmperf-mock-llm:1.1`) |
| `k6/` | scenariusze ruchu (otwarty, zamknięty, rampa, mieszany, długie, strumień, gunicorn, incydent) |
| `scripts/` | dane, nakładki stanów, pomiar z próbkowaniem, TTFT strumienia, porównanie z Claude |
| `exercises/` | 18 ćwiczeń + `00-teoria.md` + 5 czytanek `NNa-*.md` |
| `EXERCISES.md` | spis ćwiczeń, czasy, mapa umiejętności |
| `slownik.md` | słownik pojęć z odnośnikami do ćwiczeń |
| `solutions/` | rozwiązania kumulatywne, podpowiedzi, odpowiedzi do pytań, klucz finału |
| `check.py`, `smoke.sh`, `incydent.sh` | weryfikacja „done”, regresja, incydenty |
| `gunicorn.conf.py` | konfiguracja wariantu gunicorn (ćw. 07) |
| `docker-compose.yml`, `grafana/` | stos obserwowalności, Redis, atrapa, k6; dashboardy i scrape |
| `wyniki/` | podsumowania k6 i przebiegów (nie w repo) |

## Uwagi

- **Czas:** ćwiczenia z mini-incydentami ~16 h, czytanki ~3.5 h. Ćw. 10, 12 i 18 zawierają testy wielominutowe
  (dopływ 3–4 min + opróżnianie) — tak ma być: wywołania LLM trwające minuty to część tematu kursu.
- **Koszt:** zero przy pracy na atrapie. Opcjonalne ćw. 17 na prawdziwym Claude (`claude-haiku-5-5`, 24 wywołania
  sekwencyjnie) ≈ $0.005 — klucz trzymaj tylko w bieżącej powłoce, nigdy w repo.
- **Porty** (wszystkie na 127.0.0.1): aplikacja 8060, atrapa LLM 8061, gunicorn 8062, metryki workera 8063,
  Grafana 3060, OTLP 4367 (gRPC) / 4368 (HTTP), Prometheus 9196, Pyroscope 4060, Redis 6460. Wybrano je tak,
  by nie kolidowały z innymi stosami, które możesz mieć uruchomione; jeśli coś u Ciebie zajmuje któryś z nich,
  zmień wartość w `.env` (compose czyta `*_PORT`) i odpowiednie adresy (`LLM_BASE_URL`, `REDIS_URL`, `OTEL_*`).
  Nie uruchamiaj kilku ciężkich stacków obserwowalności naraz.
- **Znane ograniczenie: `dial: i/o timeout` w k6 (Docker Desktop).** k6 w kontenerze łączy się z aplikacją na
  hoście przez `host.docker.internal`. Przy setkach NOWYCH połączeń w krótkim czasie Docker Desktop czasem nie
  zestawia części z nich: w podsumowaniu k6 to `status 0` (np. `status_krotkie_0`), a w logu k6
  `dial: i/o timeout`. Zmierzone: 0.66% żądań w rampie, ~4% w 240-sekundowym incydencie — w obu wariantach
  (z wadami i naprawionym). Jak odróżnić od wady aplikacji: aplikacja **nie rejestruje** tych żądań
  (`app_requests_total` i `/diag` ich nie liczą, brak trace'ów), występują w podobnej liczbie przed i po naprawie,
  nie mają `Server-Timing`. Wada aplikacji daje odpowiedź (503/504/502) albo trace z długim czekaniem.
  W raportach podawaj `status 0` osobno.
- **k6 a długie żądania:** k6 ma domyślnie 60 s timeoutu żądania i 30 s `gracefulStop` — skrypty kursu ustawiają
  własne wartości (dłuższe niż najdłuższe żądanie), inaczej k6 zrywa minutowe żądania i fałszuje drain.
- **macOS:** porty 5000/7000 zajmuje AirPlay — kurs ich nie używa.
