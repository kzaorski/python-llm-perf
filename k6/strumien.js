// Ćw. 13 — TTFT widziany przez KLIENTA strumienia (POST /claims/{n}/reply/stream, SSE).
// UWAGA (zmierzone): http_req_waiting to czas do NAGŁÓWKÓW odpowiedzi, a StreamingResponse wysyła je od razu —
// k6 nie widzi, kiedy przyszło pierwsze zdarzenie SSE. Ten scenariusz daje ruch i czas całkowity; TTFT klienta
// mierz metryką aplikacji app_stream_first_chunk_seconds (vs llm_ttft_seconds) albo scripts/strumien_ttft.py.
//
//   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/strumien.js   (-e RATE=2 -e CZAS=30s)
import http from 'k6/http';
import { Trend } from 'k6/metrics';
import { APP, podsumowanie } from './lib.js';

const ttfb = new Trend('klient_ttfb', true);
const calosc = new Trend('klient_calosc', true);

export const options = {
  scenarios: {
    strumien: { executor: 'constant-arrival-rate', rate: parseInt(__ENV.RATE || '2'), timeUnit: '1s',
                duration: __ENV.CZAS || '30s', preAllocatedVUs: 20, maxVUs: 200 },
  },
  tags: { cwiczenie: '13' },
  summaryTrendStats: ['avg', 'p(50)', 'p(90)', 'p(99)', 'max', 'count'],
};

export default function () {
  const n = 1 + Math.floor(Math.random() * 20000);
  const r = http.post(`${APP}/claims/${n}/reply/stream`, null, { timeout: '120s', tags: { endpoint: 'reply-stream' } });
  ttfb.add(r.timings.waiting);
  calosc.add(r.timings.duration);
}

export const handleSummary = podsumowanie('ex13-strumien');
