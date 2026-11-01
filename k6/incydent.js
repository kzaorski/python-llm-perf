// Ruch incydentu (./incydent.sh ruch) — model otwarty, ~4 min, kilka endpointów naraz:
//   streszczenia 8/s, odpowiedzi strumieniem 1/s, FAQ 5/s (5 popularnych pytań), analizy 1 na 10 s
//   (klient analiz rezygnuje po 30 s — jak przeglądarka/proxy z krótkim limitem).
import http from 'k6/http';
import exec from 'k6/execution';
import { Trend } from 'k6/metrics';
import { APP, zapisz, podsumowanie } from './lib.js';

const CZAS = __ENV.CZAS || '240s';
const caloscStrumienia = new Trend('klient_calosc_strumien', true);
const PYTANIA = ['jak zgłosić szkodę z OC sprawcy', 'ile trwa likwidacja szkody', 'czy należy mi się auto zastępcze',
                 'jak odwołać się od decyzji', 'jakie dokumenty do szkody mieszkaniowej'];

export const options = {
  scenarios: {
    streszczenia: { executor: 'constant-arrival-rate', rate: 8, timeUnit: '1s', duration: CZAS,
                    preAllocatedVUs: 50, maxVUs: 3000, exec: 'streszczenie' },
    strumien: { executor: 'constant-arrival-rate', rate: 1, timeUnit: '1s', duration: CZAS,
                preAllocatedVUs: 5, maxVUs: 300, exec: 'strumien' },
    faq: { executor: 'constant-arrival-rate', rate: 5, timeUnit: '1s', duration: CZAS,
           preAllocatedVUs: 10, maxVUs: 1000, exec: 'faq' },
    analizy: { executor: 'constant-arrival-rate', rate: 6, timeUnit: '1m', duration: CZAS,
               preAllocatedVUs: 5, maxVUs: 100, exec: 'analiza' },
  },
  tags: { scenariusz: 'incydent' },
  summaryTrendStats: ['avg', 'p(50)', 'p(90)', 'p(99)', 'max', 'count'],
};

export function streszczenie() {
  const i = exec.scenario.iterationInTest;
  zapisz(http.post(`${APP}/claims/${1 + (i % 20000)}/summary`, null,
    { timeout: '120s', tags: { endpoint: 'summary' } }), 'krotkie');
}

export function strumien() {
  const i = exec.scenario.iterationInTest;
  const r = http.post(`${APP}/claims/${1 + (i % 20000)}/reply/stream`, null, { timeout: '120s', tags: { endpoint: 'reply-stream' } });
  caloscStrumienia.add(r.timings.duration);
}

export function faq() {
  const i = exec.scenario.iterationInTest;
  zapisz(http.get(`${APP}/faq?q=${encodeURIComponent(PYTANIA[i % PYTANIA.length])}`,
    { timeout: '120s', tags: { endpoint: 'faq' } }), 'krotkie');
}

export function analiza() {
  const i = exec.scenario.iterationInTest;
  zapisz(http.post(`${APP}/claims/${1 + (i % 20000)}/analysis`, null, {
    headers: { 'x-mock-total-s': '120', 'x-mock-ttft-ms': '2000', 'x-mock-output-tokens': '3000' },
    timeout: '30s', tags: { endpoint: 'analysis' } }), 'dlugie');
}

export const handleSummary = podsumowanie('incydent');
