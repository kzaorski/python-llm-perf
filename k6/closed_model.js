// Ex. 02 — the CLOSED model: a constant number of virtual users (VUs), each waits for the response
// and only then sends the next request (+ a pause). Nominally: VUS / (response_time + PAUSE_S) requests/s.
//
//   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/closed_model.js
//   (variables: -e VUS=4 -e PAUSE_S=1 -e DURATION=60s)
//
// Metrics reach Prometheus with the tag model="closed" (comparison in Grafana / check.py 02).
import http from 'k6/http';
import { sleep } from 'k6';
import { APP, record, summarize } from './lib.js';

const VUS = parseInt(__ENV.VUS || '4');
const PAUSE_S = parseFloat(__ENV.PAUSE_S || '1');

export const options = {
  scenarios: {
    closed: { executor: 'constant-vus', vus: VUS, duration: __ENV.DURATION || '60s', gracefulStop: '130s' },
  },
  tags: { model: 'closed', exercise: '02' },
  summaryTrendStats: ['avg', 'p(50)', 'p(90)', 'p(99)', 'max', 'count'],
};

export default function () {
  const n = 1 + Math.floor(Math.random() * 20000);
  const r = http.post(`${APP}/claims/${n}/summary`, null, { timeout: '120s', tags: { endpoint: 'summary' } });
  record(r, 'short');
  sleep(PAUSE_S);
}

export const handleSummary = summarize('ex02-closed');
