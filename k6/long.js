// Ex. 10 — multi-minute calls (the long class, POST /claims/{n}/analysis).
// We control the mock's response time with headers that the app passes on:
//   x-mock-ttft-ms  — silence before the first token,   x-mock-total-s — the total generation time.
//
//   docker compose run --rm k6 run /scripts/long.js -e N=4 -e TTFT_MS=90000 -e TOTAL_S=30
//   docker compose run --rm k6 run /scripts/long.js -e N=6 -e TOTAL_S=150 -e K6_TIMEOUT=20s   # the client disconnects
//
// NOTE: the default k6 request timeout is 60 s — with minute-long calls ALWAYS set params.timeout.
// K6_TIMEOUT (default 400s) > the app's deadline for long calls — otherwise k6 ends the test, not the app.
import http from 'k6/http';
import { APP, record, summarize } from './lib.js';

const N = parseInt(__ENV.N || '4');

export const options = {
  scenarios: {
    long: { executor: 'per-vu-iterations', vus: N, iterations: 1, maxDuration: '20m' },
  },
  tags: { exercise: '10' },
  summaryTrendStats: ['avg', 'p(50)', 'p(90)', 'p(99)', 'max', 'count'],
};

export default function () {
  const headers = {};
  if (__ENV.TTFT_MS) headers['x-mock-ttft-ms'] = __ENV.TTFT_MS;
  if (__ENV.TOTAL_S) headers['x-mock-total-s'] = __ENV.TOTAL_S;
  headers['x-mock-output-tokens'] = __ENV.TOKENS || '3000';
  const r = http.post(`${APP}/claims/${__VU}/analysis`, null,
    { headers, timeout: __ENV.K6_TIMEOUT || '400s', tags: { endpoint: 'analysis' } });
  record(r, 'long');
  console.log(`VU ${__VU}: status=${r.status} time=${(r.timings.duration / 1000).toFixed(1)}s ${r.error || ''}`);
}

export const handleSummary = summarize('ex10-long');
