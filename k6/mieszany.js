// Ćw. 12 / finał — ruch MIESZANY w modelu otwartym: krótkie streszczenia + wielominutowe analizy.
// Harmonogram jest deterministyczny (ziarno SEED): ta sama sekwencja czasów w każdym przebiegu.
//
//   docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/mieszany.js
//   (zmienne: -e KROTKIE_RPS=4 -e DLUGIE_RPS=0.4 -e CZAS=180s -e DLUGIE_OD_S=60 -e DLUGIE_DO_S=240)
//
// Długie analizy: x-mock-total-s ~ U[DLUGIE_OD_S, DLUGIE_DO_S] (strumień tokenów bez długiej ciszy),
// TTFT 1–5 s. Krótkie: domyślny profil atrapy (~1.6 s). Timeout k6: krótkie 400 s, długie 400 s —
// celowo powyżej deadline'ów aplikacji, żeby mierzyć aplikację, a nie cierpliwość k6.
// Raport: czasy z Server-Timing per klasa (app_czekanie_*, app_ttft_*, app_total_*), statusy per klasa,
// osiągnięte tempo i dropped_iterations; zaległość po końcu dopływu — scripts/pomiar.py (próbkuje /diag).
import http from 'k6/http';
import exec from 'k6/execution';
import { APP, zapisz, podsumowanie, rng } from './lib.js';

const KR = parseFloat(__ENV.KROTKIE_RPS || '4');
const DL = parseFloat(__ENV.DLUGIE_RPS || '0.4');
const CZAS = __ENV.CZAS || '180s';
const OD = parseFloat(__ENV.DLUGIE_OD_S || '60');
const DO = parseFloat(__ENV.DLUGIE_DO_S || '240');
const SEED = parseInt(__ENV.SEED || '20261101');

// tempo ułamkowe → rate na minutę
export const options = {
  scenarios: {
    krotkie: { executor: 'constant-arrival-rate', rate: Math.round(KR * 60), timeUnit: '1m', duration: CZAS,
               preAllocatedVUs: 50, maxVUs: 3000, exec: 'krotkie' },
    dlugie: { executor: 'constant-arrival-rate', rate: Math.round(DL * 60), timeUnit: '1m', duration: CZAS,
              preAllocatedVUs: 20, maxVUs: 500, exec: 'dlugie' },
  },
  tags: { scenariusz: 'mieszany' },
  summaryTrendStats: ['avg', 'p(50)', 'p(90)', 'p(99)', 'max', 'count'],
};

export function krotkie() {
  const i = exec.scenario.iterationInTest;
  const r = http.post(`${APP}/claims/${1 + (i % 20000)}/summary`, null,
    { timeout: __ENV.K6_TIMEOUT || '400s', tags: { endpoint: 'summary', klasa: 'krotkie' } });
  zapisz(r, 'krotkie');
}

export function dlugie() {
  const i = exec.scenario.iterationInTest;
  const los = rng(SEED + i);
  const total = OD + los() * (DO - OD);
  const ttft = 1000 + los() * 4000;
  const r = http.post(`${APP}/claims/${1 + (i % 20000)}/analysis`, null, {
    headers: { 'x-mock-total-s': total.toFixed(1), 'x-mock-ttft-ms': ttft.toFixed(0), 'x-mock-output-tokens': '3000' },
    timeout: __ENV.K6_TIMEOUT || '400s', tags: { endpoint: 'analysis', klasa: 'dlugie' } });
  zapisz(r, 'dlugie');
}

export const handleSummary = podsumowanie('ex12-mieszany');
