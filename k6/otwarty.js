// Ćw. 02 — model OTWARTY: żądania przychodzą w zadanym tempie NIEZALEŻNIE od tego, czy poprzednie
// już wróciły (tak jak prawdziwi klienci). Tylko taki model pokazuje kolejkę i prawdziwy ogon.
//
//   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/otwarty.js
//   (zmienne: -e RATE=4 -e CZAS=60s)
//
// TODO ćw. 02: uzupełnij `options.scenarios` — executor otwarty o stałym tempie RATE żądań/s przez CZAS,
//   z pulą VU wystarczającą, by k6 nie gubił iteracji (metryka dropped_iterations musi zostać 0).
//   Tag modelu: model="otwarty".
import http from 'k6/http';
import { APP, zapisz, podsumowanie } from '/scripts/lib.js';  // ścieżka w kontenerze k6 (./k6 → /scripts)

const RATE = parseInt(__ENV.RATE || '4');

export const options = {
  scenarios: {
    // TODO ćw. 02
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
