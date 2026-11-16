// Ex. 02 — the OPEN model: requests arrive at the given rate REGARDLESS of whether the previous ones
// have returned yet (like real customers). Only this model shows the queue and the true tail.
//
//   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/open_model.js
//   (variables: -e RATE=4 -e DURATION=60s)
//
// [SOLUTION ex. 02 — copy to k6/open_model.js]
import http from 'k6/http';
import { APP, record, summarize } from '/scripts/lib.js';  // the path in the k6 container (./k6 → /scripts)

const RATE = parseInt(__ENV.RATE || '4');

export const options = {
  scenarios: {
    // ex. 02 (F14) ✅: constant-arrival-rate = the open model. preAllocatedVUs/maxVUs ≥ RATE × the worst
    // response time (Little: L = λ·W), otherwise k6 itself "closes" the model and drops iterations (dropped_iterations).
    open: { executor: 'constant-arrival-rate', rate: RATE, timeUnit: '1s', duration: __ENV.DURATION || '60s',
            preAllocatedVUs: Math.max(10, RATE * 10), maxVUs: Math.max(200, RATE * 60), gracefulStop: '130s' },
  },
  tags: { model: 'open', exercise: '02' },
  summaryTrendStats: ['avg', 'p(50)', 'p(90)', 'p(99)', 'max', 'count'],
};

export function setup() {
  if (Object.keys(options.scenarios).length === 0) {
    throw new Error('TODO ex. 02: fill in options.scenarios in k6/open_model.js (an open-model executor)');
  }
}

export default function () {
  const n = 1 + Math.floor(Math.random() * 20000);
  const r = http.post(`${APP}/claims/${n}/summary`, null, { timeout: '120s', tags: { endpoint: 'summary' } });
  record(r, 'short');
}

export const handleSummary = summarize('ex02-open');
