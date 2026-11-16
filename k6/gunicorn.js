// Ex. 07 — comparing gunicorn process models (port 8062) in the open model.
//
//   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/gunicorn.js -e RATE=20 -e DURATION=60s
//   (-e ENDPOINT_PATH=reply — longer responses ~3.3 s; -e VARIANT=sync|uvicorn goes into the tag)
import http from 'k6/http';
import { summarize, record } from './lib.js';

const URL = __ENV.GUNICORN_URL || 'http://host.docker.internal:8062';
const ENDPOINT_PATH = __ENV.ENDPOINT_PATH || 'summary';

export const options = {
  scenarios: {
    gunicorn: { executor: 'constant-arrival-rate', rate: parseInt(__ENV.RATE || '20'), timeUnit: '1s',
                duration: __ENV.DURATION || '60s', preAllocatedVUs: 200, maxVUs: 3000, gracefulStop: '420s' },
  },
  tags: { exercise: '07', variant: __ENV.VARIANT || 'unknown' },
  summaryTrendStats: ['avg', 'p(50)', 'p(90)', 'p(99)', 'max', 'count'],
};

export default function () {
  const n = 1 + Math.floor(Math.random() * 20000);
  const headers = __ENV.TOTAL_S ? { 'x-mock-total-s': __ENV.TOTAL_S } : {};
  const r = http.post(`${URL}/claims/${n}/${ENDPOINT_PATH}`, null, { headers, timeout: '400s', tags: { endpoint: ENDPOINT_PATH } });
  record(r, 'short');
}

export const handleSummary = summarize(`ex07-gunicorn-${__ENV.VARIANT || 'unknown'}`);
