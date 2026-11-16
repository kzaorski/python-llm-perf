// Incident traffic (./incident.sh traffic) — the open model, ~4 min, several endpoints at once:
//   summaries 8/s, stream replies 1/s, FAQ 5/s (5 popular questions), analyses 1 per 10 s
//   (the analysis client gives up after 30 s — like a browser/proxy with a short limit).
import http from 'k6/http';
import exec from 'k6/execution';
import { Trend } from 'k6/metrics';
import { APP, record, summarize } from './lib.js';

const DURATION = __ENV.DURATION || '240s';
const streamTotal = new Trend('client_total_stream', true);
const QUESTIONS = ["how to file a claim with the at-fault party's insurer", 'how long does claim settlement take',
                   'am I entitled to a rental car', 'how to appeal a decision', 'which documents are needed for a home claim'];

export const options = {
  scenarios: {
    summaries: { executor: 'constant-arrival-rate', rate: 8, timeUnit: '1s', duration: DURATION,
                 preAllocatedVUs: 300, maxVUs: 3000, exec: 'summary', gracefulStop: '150s' },
    stream: { executor: 'constant-arrival-rate', rate: 1, timeUnit: '1s', duration: DURATION,
              preAllocatedVUs: 50, maxVUs: 300, exec: 'stream', gracefulStop: '150s' },
    faq: { executor: 'constant-arrival-rate', rate: 5, timeUnit: '1s', duration: DURATION,
           preAllocatedVUs: 100, maxVUs: 1000, exec: 'faq', gracefulStop: '150s' },
    analyses: { executor: 'constant-arrival-rate', rate: 6, timeUnit: '1m', duration: DURATION,
                preAllocatedVUs: 20, maxVUs: 100, exec: 'analysis', gracefulStop: '150s' },
  },
  tags: { scenario: 'incident' },
  summaryTrendStats: ['avg', 'p(50)', 'p(90)', 'p(99)', 'max', 'count'],
};

export function summary() {
  const i = exec.scenario.iterationInTest;
  record(http.post(`${APP}/claims/${1 + (i % 20000)}/summary`, null,
    { timeout: '120s', tags: { endpoint: 'summary' } }), 'short');
}

export function stream() {
  const i = exec.scenario.iterationInTest;
  const r = http.post(`${APP}/claims/${1 + (i % 20000)}/reply/stream`, null, { timeout: '120s', tags: { endpoint: 'reply-stream' } });
  streamTotal.add(r.timings.duration);
}

export function faq() {
  const i = exec.scenario.iterationInTest;
  record(http.get(`${APP}/faq?q=${encodeURIComponent(QUESTIONS[i % QUESTIONS.length])}`,
    { timeout: '120s', tags: { endpoint: 'faq' } }), 'short');
}

export function analysis() {
  const i = exec.scenario.iterationInTest;
  record(http.post(`${APP}/claims/${1 + (i % 20000)}/analysis`, null, {
    headers: { 'x-mock-total-s': '120', 'x-mock-ttft-ms': '2000', 'x-mock-output-tokens': '3000' },
    timeout: '30s', tags: { endpoint: 'analysis' } }), 'long');
}

export const handleSummary = summarize('incident');
