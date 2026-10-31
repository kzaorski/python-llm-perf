// Test dymny k6: czy kontener k6 widzi aplikację (host) i atrapę LLM (sieć compose),
// a metryki trafiają do Prometheusa (remote write).
// Uruchom:  docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/smoke.js
import http from 'k6/http';
import { check } from 'k6';
import { SharedArray } from 'k6/data';

const claims = new SharedArray('zgloszenia', () => JSON.parse(open('/data/k6_zgloszenia.json')));
const APP = __ENV.APP_URL || 'http://host.docker.internal:8060';
const MOCK = __ENV.MOCK_URL || 'http://mock-llm:8061';

export const options = {
  scenarios: {
    dymny: { executor: 'constant-arrival-rate', rate: 5, timeUnit: '1s', duration: '10s',
             preAllocatedVUs: 10, maxVUs: 50 },
  },
  thresholds: {
    checks: ['rate==1.0'],
    'http_req_duration{cel:mock}': ['p(99)<5000'],
  },
  summaryTrendStats: ['avg', 'p(50)', 'p(90)', 'p(99)', 'max'],
};

export default function () {
  const h = http.get(`${APP}/health`, { tags: { cel: 'app' } });
  check(h, { 'app /health 200': (r) => r.status === 200 && r.json('status') === 'ok' });

  const c = claims[Math.floor(Math.random() * claims.length)];
  const body = JSON.stringify({
    model: 'claude-haiku-5-5', max_tokens: 64,
    messages: [{ role: 'user', content: `Sklasyfikuj zgłoszenie jednym słowem.\n\n${c.opis}` }],
  });
  const m = http.post(`${MOCK}/v1/messages`, body, {
    headers: { 'content-type': 'application/json', 'x-api-key': 'mock-key', 'anthropic-version': '2023-06-01' },
    tags: { cel: 'mock' },
  });
  check(m, { 'atrapa 200 + usage': (r) => r.status === 200 && r.json('usage.output_tokens') > 0 });
}
