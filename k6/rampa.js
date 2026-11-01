// Ćw. 03 — rampa tempa (ramping-arrival-rate): szukamy „kolana" krzywej wykorzystanie → czas oczekiwania.
// Tempo rośnie schodkami co KROK_S sekund od OD do DO żądań/s (model otwarty).
//
//   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/rampa.js
//   (zmienne: -e OD=2 -e DO=30 -e SKOK=4 -e KROK_S=30)
//
// W Grafanie zestaw: tempo (k6_http_reqs_total), wykorzystanie slotów (llm_inflight / LLM_SLOTY),
// czekanie (llm_queue_wait_seconds) i p99 k6 — kolano to miejsce, gdzie czekanie rośnie szybciej niż tempo.
import http from 'k6/http';
import { APP, zapisz, podsumowanie } from './lib.js';

const OD = parseInt(__ENV.OD || '2');
const DO = parseInt(__ENV.DO || '30');
const SKOK = parseInt(__ENV.SKOK || '4');
const KROK_S = parseInt(__ENV.KROK_S || '30');

const stages = [];
for (let r = OD; r <= DO; r += SKOK) {
  stages.push({ target: r, duration: '2s' });
  stages.push({ target: r, duration: `${KROK_S}s` });
}

export const options = {
  scenarios: {
    rampa: { executor: 'ramping-arrival-rate', startRate: OD, timeUnit: '1s', stages,
             preAllocatedVUs: 200, maxVUs: 2000, gracefulStop: '130s' },
  },
  tags: { model: 'otwarty', scenariusz: 'rampa', cwiczenie: '03' },
  summaryTrendStats: ['avg', 'p(50)', 'p(90)', 'p(99)', 'max', 'count'],
};

export default function () {
  const n = 1 + Math.floor(Math.random() * 20000);
  const r = http.post(`${APP}/claims/${n}/summary`, null, { timeout: '120s', tags: { endpoint: 'summary' } });
  zapisz(r, 'krotkie');
}

export const handleSummary = podsumowanie('ex03-rampa');
