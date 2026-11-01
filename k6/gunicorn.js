// Ćw. 07 — porównanie modeli procesów gunicorna (port 8062) w modelu otwartym.
//
//   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/gunicorn.js -e RATE=20 -e CZAS=60s
//   (-e SCIEZKA=reply — dłuższe odpowiedzi ~3.3 s; -e WARIANT=sync|uvicorn trafia do tagu)
import http from 'k6/http';
import { podsumowanie, zapisz } from './lib.js';

const URL = __ENV.GUNICORN_URL || 'http://host.docker.internal:8062';
const SCIEZKA = __ENV.SCIEZKA || 'summary';

export const options = {
  scenarios: {
    gunicorn: { executor: 'constant-arrival-rate', rate: parseInt(__ENV.RATE || '20'), timeUnit: '1s',
                duration: __ENV.CZAS || '60s', preAllocatedVUs: 200, maxVUs: 3000, gracefulStop: '420s' },
  },
  tags: { cwiczenie: '07', wariant: __ENV.WARIANT || 'nieznany' },
  summaryTrendStats: ['avg', 'p(50)', 'p(90)', 'p(99)', 'max', 'count'],
};

export default function () {
  const n = 1 + Math.floor(Math.random() * 20000);
  const headers = __ENV.TOTAL_S ? { 'x-mock-total-s': __ENV.TOTAL_S } : {};
  const r = http.post(`${URL}/claims/${n}/${SCIEZKA}`, null, { headers, timeout: '400s', tags: { endpoint: SCIEZKA } });
  zapisz(r, 'krotkie');
}

export const handleSummary = podsumowanie(`ex07-gunicorn-${__ENV.WARIANT || 'nieznany'}`);
