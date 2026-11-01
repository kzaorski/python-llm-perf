// Ćw. 02 — model OTWARTY: żądania przychodzą w zadanym tempie NIEZALEŻNIE od tego, czy poprzednie
// już wróciły (tak jak prawdziwi klienci). Tylko taki model pokazuje kolejkę i prawdziwy ogon.
//
//   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/otwarty.js
//   (zmienne: -e RATE=4 -e CZAS=60s)
//
// [ROZWIĄZANIE ćw. 02 — kopiuj do k6/otwarty.js]
import http from 'k6/http';
import { APP, zapisz, podsumowanie } from '/scripts/lib.js';  // ścieżka w kontenerze k6 (./k6 → /scripts)

const RATE = parseInt(__ENV.RATE || '4');

export const options = {
  scenarios: {
    // ćw. 02 (W14) ✅: constant-arrival-rate = model otwarty. preAllocatedVUs/maxVUs ≥ RATE × najgorszy
    // czas odpowiedzi (Little: L = λ·W), inaczej k6 sam „zamyka" model i gubi iteracje (dropped_iterations).
    otwarty: { executor: 'constant-arrival-rate', rate: RATE, timeUnit: '1s', duration: __ENV.CZAS || '60s',
               preAllocatedVUs: Math.max(10, RATE * 10), maxVUs: Math.max(200, RATE * 60), gracefulStop: '130s' },
  },
  tags: { model: 'otwarty', cwiczenie: '02' },
  summaryTrendStats: ['avg', 'p(50)', 'p(90)', 'p(99)', 'max', 'count'],
};

export function setup() {
  if (Object.keys(options.scenarios).length === 0) {
    throw new Error('TODO ćw. 02: uzupełnij options.scenarios w k6/otwarty.js (executor modelu otwartego)');
  }
}

export default function () {
  const n = 1 + Math.floor(Math.random() * 20000);
  const r = http.post(`${APP}/claims/${n}/summary`, null, { timeout: '120s', tags: { endpoint: 'summary' } });
  zapisz(r, 'krotkie');
}

export const handleSummary = podsumowanie('ex02-otwarty');
