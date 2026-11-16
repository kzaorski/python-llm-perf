// Ex. 13 — TTFT as seen by the stream's CLIENT (POST /claims/{n}/reply/stream, SSE).
// NOTE (measured): http_req_waiting is the time to the response HEADERS, and StreamingResponse sends them right away —
// k6 does not see when the first SSE event arrived. This scenario gives traffic and the total time; measure the client TTFT
// with the app metric app_stream_first_chunk_seconds (vs llm_ttft_seconds) or scripts/stream_ttft.py.
//
//   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/stream.js   (-e RATE=2 -e DURATION=30s)
import http from 'k6/http';
import { Trend } from 'k6/metrics';
import { APP, summarize } from './lib.js';

const ttfb = new Trend('client_ttfb', true);
const total = new Trend('client_total', true);

export const options = {
  scenarios: {
    stream: { executor: 'constant-arrival-rate', rate: parseInt(__ENV.RATE || '2'), timeUnit: '1s',
              duration: __ENV.DURATION || '30s', preAllocatedVUs: 20, maxVUs: 200, gracefulStop: '130s' },
  },
  tags: { exercise: '13' },
  summaryTrendStats: ['avg', 'p(50)', 'p(90)', 'p(99)', 'max', 'count'],
};

export default function () {
  const n = 1 + Math.floor(Math.random() * 20000);
  const r = http.post(`${APP}/claims/${n}/reply/stream`, null, { timeout: '120s', tags: { endpoint: 'reply-stream' } });
  ttfb.add(r.timings.waiting);
  total.add(r.timings.duration);
}

export const handleSummary = summarize('ex13-stream');
