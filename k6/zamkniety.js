// Ćw. 02 — model ZAMKNIĘTY: stała liczba wirtualnych użytkowników (VU), każdy czeka na odpowiedź
// i dopiero wtedy wysyła kolejne żądanie (+ pauza). Nominalnie: VUS / (czas_odpowiedzi + PAUZA) żądań/s.
//
//   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/zamkniety.js
//   (zmienne: -e VUS=4 -e PAUZA_S=1 -e CZAS=60s)
//
// Metryki trafiają do Prometheusa z tagiem model="zamkniety" (porównanie w Grafanie / check.py 02).
import http from 'k6/http';
import { sleep } from 'k6';
import { APP, zapisz, podsumowanie } from './lib.js';

const VUS = parseInt(__ENV.VUS || '4');
const PAUZA_S = parseFloat(__ENV.PAUZA_S || '1');

export const options = {
  scenarios: {
    zamkniety: { executor: 'constant-vus', vus: VUS, duration: __ENV.CZAS || '60s', gracefulStop: '130s' },
  },
  tags: { model: 'zamkniety', cwiczenie: '02' },
  summaryTrendStats: ['avg', 'p(50)', 'p(90)', 'p(99)', 'max', 'count'],
};

export default function () {
  const n = 1 + Math.floor(Math.random() * 20000);
  const r = http.post(`${APP}/claims/${n}/summary`, null, { timeout: '120s', tags: { endpoint: 'summary' } });
  zapisz(r, 'krotkie');
  sleep(PAUZA_S);
}

export const handleSummary = podsumowanie('ex02-zamkniety');
