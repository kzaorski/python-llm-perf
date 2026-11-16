// Ex. 12 / final — MIXED traffic in the open model: short summaries + multi-minute analyses.
// The schedule is deterministic (seed SEED): the same sequence of times in every run.
//
//   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/mixed.js
//   (variables: -e SHORT_RPS=4 -e LONG_RPS=0.4 -e DURATION=180s -e LONG_MIN_S=60 -e LONG_MAX_S=240)
//
// Long analyses: x-mock-total-s ~ U[LONG_MIN_S, LONG_MAX_S] (a token stream without a long silence),
// TTFT 1–5 s. Short: the mock's default profile (~1.6 s). k6 timeout: short 400 s, long 400 s —
// deliberately above the app's deadlines, so that we measure the app, not k6's patience.
// Report: Server-Timing times per class (app_wait_*, app_ttft_*, app_total_*), statuses per class,
// the achieved rate and dropped_iterations; gracefulStop 420 s — k6 does NOT abort in-flight requests after the end of inflow
// (the default 30 s would cut multi-minute requests and falsify the backlog measurement); the backlog after the end of inflow — scripts/measure.py (samples /diag).
import http from 'k6/http';
import exec from 'k6/execution';
import { APP, record, summarize, rng } from './lib.js';

const SHORT_RATE = parseFloat(__ENV.SHORT_RPS || '4');
const LONG_RATE = parseFloat(__ENV.LONG_RPS || '0.4');
const DURATION = __ENV.DURATION || '180s';
const LONG_MIN = parseFloat(__ENV.LONG_MIN_S || '60');
const LONG_MAX = parseFloat(__ENV.LONG_MAX_S || '240');
const SEED = parseInt(__ENV.SEED || '20261101');

// a fractional rate → rate per minute
export const options = {
  scenarios: {
    short: { executor: 'constant-arrival-rate', rate: Math.round(SHORT_RATE * 60), timeUnit: '1m', duration: DURATION,
             preAllocatedVUs: 300, maxVUs: 3000, exec: 'short', gracefulStop: '420s' },
    long: { executor: 'constant-arrival-rate', rate: Math.round(LONG_RATE * 60), timeUnit: '1m', duration: DURATION,
            preAllocatedVUs: 100, maxVUs: 500, exec: 'long', gracefulStop: '420s' },
  },
  tags: { scenario: 'mixed' },
  summaryTrendStats: ['avg', 'p(50)', 'p(90)', 'p(99)', 'max', 'count'],
};

export function short() {
  const i = exec.scenario.iterationInTest;
  const r = http.post(`${APP}/claims/${1 + (i % 20000)}/summary`, null,
    { timeout: __ENV.K6_TIMEOUT || '400s', tags: { endpoint: 'summary', request_class: 'short' } });
  record(r, 'short');
}

export function long() {
  const i = exec.scenario.iterationInTest;
  const rand = rng(SEED + i);
  const total = LONG_MIN + rand() * (LONG_MAX - LONG_MIN);
  const ttft = 1000 + rand() * 4000;
  const r = http.post(`${APP}/claims/${1 + (i % 20000)}/analysis`, null, {
    headers: { 'x-mock-total-s': total.toFixed(1), 'x-mock-ttft-ms': ttft.toFixed(0), 'x-mock-output-tokens': '3000' },
    timeout: __ENV.K6_TIMEOUT || '400s', tags: { endpoint: 'analysis', request_class: 'long' } });
  record(r, 'long');
}

export const handleSummary = summarize('ex12-mixed');
