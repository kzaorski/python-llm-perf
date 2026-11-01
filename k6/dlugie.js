// Ćw. 10 — wywołania wielominutowe (klasa długa, POST /claims/{n}/analysis).
// Czas odpowiedzi atrapy sterujemy nagłówkami przekazywanymi przez aplikację:
//   x-mock-ttft-ms  — cisza przed pierwszym tokenem,   x-mock-total-s — łączny czas generowania.
//
//   docker compose run --rm k6 run /scripts/dlugie.js -e N=4 -e TTFT_MS=90000 -e TOTAL_S=30
//   docker compose run --rm k6 run /scripts/dlugie.js -e N=6 -e TOTAL_S=150 -e K6_TIMEOUT=20s   # klient się rozłącza
//
// UWAGA: domyślny timeout żądania k6 to 60 s — przy wywołaniach minutowych ZAWSZE ustawiaj params.timeout.
// K6_TIMEOUT (domyślnie 400s) > deadline aplikacji dla długich — inaczej to k6 przerwie test, a nie aplikacja.
import http from 'k6/http';
import { APP, zapisz, podsumowanie } from './lib.js';

const N = parseInt(__ENV.N || '4');

export const options = {
  scenarios: {
    dlugie: { executor: 'per-vu-iterations', vus: N, iterations: 1, maxDuration: '20m' },
  },
  tags: { cwiczenie: '10' },
  summaryTrendStats: ['avg', 'p(50)', 'p(90)', 'p(99)', 'max', 'count'],
};

export default function () {
  const headers = {};
  if (__ENV.TTFT_MS) headers['x-mock-ttft-ms'] = __ENV.TTFT_MS;
  if (__ENV.TOTAL_S) headers['x-mock-total-s'] = __ENV.TOTAL_S;
  headers['x-mock-output-tokens'] = __ENV.TOKENY || '3000';
  const r = http.post(`${APP}/claims/${__VU}/analysis`, null,
    { headers, timeout: __ENV.K6_TIMEOUT || '400s', tags: { endpoint: 'analysis' } });
  zapisz(r, 'dlugie');
  console.log(`VU ${__VU}: status=${r.status} czas=${(r.timings.duration / 1000).toFixed(1)}s ${r.error || ''}`);
}

export const handleSummary = podsumowanie('ex10-dlugie');
