// Ex. 02 — the OPEN model: requests arrive at the given rate REGARDLESS of whether the previous ones
// have returned yet (like real customers). Only this model shows the queue and the true tail.
//
//   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/open_model.js
//   (variables: -e RATE=4 -e DURATION=60s)
//
// TODO ex. 02: fill in `options.scenarios` — an open executor with a constant rate of RATE requests/s for DURATION,
//   with a VU pool large enough that k6 does not drop iterations (the dropped_iterations metric must stay 0).
//   Model tag: model="open".
import http from 'k6/http';
import { APP, record, summarize } from '/scripts/lib.js';  // the path in the k6 container (./k6 → /scripts)

const RATE = parseInt(__ENV.RATE || '4');

export const options = {
  scenarios: {
    // TODO ex. 02
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
