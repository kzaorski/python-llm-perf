// Ex. 03 — a rate ramp (ramping-arrival-rate): we look for the "knee" of the utilization → waiting time curve.
// The rate grows in steps every STEP_S seconds from FROM to TO requests/s (open model).
//
//   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/ramp.js
//   (variables: -e FROM=2 -e TO=30 -e STEP_RPS=4 -e STEP_S=30)
//
// In Grafana put side by side: the rate (k6_http_reqs_total), slot utilization (llm_inflight / LLM_SLOTS),
// waiting (llm_queue_wait_seconds) and k6 p99 — the knee is where waiting grows faster than the rate.
import http from 'k6/http';
import { APP, record, summarize } from './lib.js';

const FROM = parseInt(__ENV.FROM || '2');
const TO = parseInt(__ENV.TO || '30');
const STEP_RPS = parseInt(__ENV.STEP_RPS || '4');
const STEP_S = parseInt(__ENV.STEP_S || '30');

const stages = [];
for (let r = FROM; r <= TO; r += STEP_RPS) {
  stages.push({ target: r, duration: '2s' });
  stages.push({ target: r, duration: `${STEP_S}s` });
}

export const options = {
  scenarios: {
    ramp: { executor: 'ramping-arrival-rate', startRate: FROM, timeUnit: '1s', stages,
            preAllocatedVUs: 200, maxVUs: 2000, gracefulStop: '130s' },
  },
  tags: { model: 'open', scenario: 'ramp', exercise: '03' },
  summaryTrendStats: ['avg', 'p(50)', 'p(90)', 'p(99)', 'max', 'count'],
};

export default function () {
  const n = 1 + Math.floor(Math.random() * 20000);
  const r = http.post(`${APP}/claims/${n}/summary`, null, { timeout: '120s', tags: { endpoint: 'summary' } });
  record(r, 'short');
}

export const handleSummary = summarize('ex03-ramp');
