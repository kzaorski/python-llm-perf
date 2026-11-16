// k6 smoke test: does the k6 container see the app (the host) and the mock LLM (the compose network),
// and do the metrics reach Prometheus (remote write).
// Run:  docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/smoke.js
import http from 'k6/http';
import { check } from 'k6';
import { SharedArray } from 'k6/data';

const claims = new SharedArray('claims', () => JSON.parse(open('/data/k6_claims.json')));
const APP = __ENV.APP_URL || 'http://host.docker.internal:8060';
const MOCK = __ENV.MOCK_URL || 'http://mock-llm:8061';

export const options = {
  scenarios: {
    smoke: { executor: 'constant-arrival-rate', rate: 5, timeUnit: '1s', duration: '10s',
             preAllocatedVUs: 10, maxVUs: 50 },
  },
  thresholds: {
    checks: ['rate==1.0'],
    'http_req_duration{target:mock}': ['p(99)<5000'],
  },
  summaryTrendStats: ['avg', 'p(50)', 'p(90)', 'p(99)', 'max'],
};

export default function () {
  const h = http.get(`${APP}/health`, { tags: { target: 'app' } });
  check(h, { 'app /health 200': (r) => r.status === 200 && r.json('status') === 'ok' });

  const c = claims[Math.floor(Math.random() * claims.length)];
  const body = JSON.stringify({
    model: 'claude-haiku-5-5', max_tokens: 64,
    messages: [{ role: 'user', content: `Classify the claim in one word.\n\n${c.description}` }],
  });
  const m = http.post(`${MOCK}/v1/messages`, body, {
    headers: { 'content-type': 'application/json', 'x-api-key': 'mock-key', 'anthropic-version': '2023-06-01' },
    tags: { target: 'mock' },
  });
  check(m, { 'mock 200 + usage': (r) => r.status === 200 && r.json('usage.output_tokens') > 0 });
}
