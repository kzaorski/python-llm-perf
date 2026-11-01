// Wspólne elementy scenariuszy k6 kursu python-llm-perf.
// - czasy z nagłówka Server-Timing aplikacji (czekanie / llm / ttft / total) jako osobne Trendy per klasa,
// - liczniki statusów per klasa (200 / 499 / 502 / 503 / 504 / 0 = timeout lub zerwanie po stronie k6),
// - handleSummary: zapis podsumowania do /wyniki/<NAZWA>.json (katalog ./wyniki w repo) + tekst na konsolę.
import { Counter, Trend } from 'k6/metrics';

export const APP = __ENV.APP_URL || 'http://host.docker.internal:8060';
export const KLASY = ['krotkie', 'dlugie'];
const KODY = [200, 429, 499, 500, 502, 503, 504, 0];

const trendy = {};
const statusy = {};
for (const k of KLASY) {
  for (const t of ['czekanie', 'llm', 'ttft', 'total']) {
    trendy[`${t}_${k}`] = new Trend(`app_${t}_${k}`, true);
  }
  for (const c of KODY) {
    statusy[`${k}_${c}`] = new Counter(`status_${k}_${c}`);
  }
}

export function serverTiming(res) {
  const h = res.headers['Server-Timing'] || res.headers['server-timing'] || '';
  const out = {};
  for (const part of h.split(',')) {
    const m = part.trim().match(/^(\w+);dur=([\d.]+)/);
    if (m) out[m[1]] = parseFloat(m[2]);
  }
  return out;
}

// Zapisuje czasy aplikacji i status żądania danej klasy.
export function zapisz(res, klasa) {
  const kod = KODY.includes(res.status) ? res.status : 500;
  statusy[`${klasa}_${kod}`].add(1);
  const st = serverTiming(res);
  for (const t of ['czekanie', 'llm', 'ttft', 'total']) {
    if (st[t] !== undefined) trendy[`${t}_${klasa}`].add(st[t]);
  }
  return st;
}

// Deterministyczny generator liczb pseudolosowych (mulberry32) — ten sam harmonogram w każdym przebiegu.
export function rng(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function podsumowanie(nazwa) {
  return function (data) {
    const plik = `/wyniki/${__ENV.WYNIK || nazwa}.json`;
    data.meta = { nazwa: __ENV.WYNIK || nazwa, koniec: new Date().toISOString(), env: { APP_URL: APP } };
    return {
      [plik]: JSON.stringify(data, null, 1),
      stdout: tekst(data),
    };
  };
}

// Zwięzłe podsumowanie na konsolę (bez zależności z sieci): trendy w ms, liczniki, tempo, dropped_iterations.
function tekst(data) {
  const m = data.metrics;
  const linie = [`\n== ${data.meta.nazwa} ==`];
  const czas_s = (data.state && data.state.testRunDurationMs || 0) / 1000;
  linie.push(`czas testu: ${czas_s.toFixed(1)} s`);
  for (const [nazwa, v] of Object.entries(m).sort()) {
    const val = v.values || {};
    if (v.type === 'trend' && val.count !== 0 && val['p(50)'] !== undefined) {
      linie.push(`${nazwa.padEnd(36)} p50=${f(val['p(50)'])} p90=${f(val['p(90)'])} p99=${f(val['p(99)'])} max=${f(val.max)}`);
    } else if (v.type === 'counter' && val.count > 0) {
      linie.push(`${nazwa.padEnd(36)} ${val.count} (${(val.rate || 0).toFixed(2)}/s)`);
    } else if (v.type === 'rate' && val.rate !== undefined) {
      linie.push(`${nazwa.padEnd(36)} ${(val.rate * 100).toFixed(2)}%`);
    }
  }
  return linie.join('\n') + '\n';
}

function f(ms) {
  if (ms === undefined || ms === null) return '-';
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms.toFixed(0)}ms`;
}
