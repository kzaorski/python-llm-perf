// Shared parts of the k6 scenarios of the python-llm-perf course.
// - times from the app's Server-Timing header (wait / llm / ttft / total) as separate Trends per class,
// - status counters per class (200 / 499 / 502 / 503 / 504 / 0 = a timeout or a dropped connection on the k6 side),
// - handleSummary: writes the summary to /results/<NAME>.json (the ./results directory in the repo) + text to the console.
import { Counter, Trend } from 'k6/metrics';

export const APP = __ENV.APP_URL || 'http://host.docker.internal:8060';
export const REQUEST_CLASSES = ['short', 'long'];
const CODES = [200, 429, 499, 500, 502, 503, 504, 0];

const trends = {};
const status_counters = {};
for (const k of REQUEST_CLASSES) {
  for (const t of ['wait', 'llm', 'ttft', 'total']) {
    trends[`${t}_${k}`] = new Trend(`app_${t}_${k}`, true);
  }
  for (const c of CODES) {
    status_counters[`${k}_${c}`] = new Counter(`status_${k}_${c}`);
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

// Records the app's times and the status of a request of the given class.
export function record(res, requestClass) {
  const code = CODES.includes(res.status) ? res.status : 500;
  status_counters[`${requestClass}_${code}`].add(1);
  const st = serverTiming(res);
  for (const t of ['wait', 'llm', 'ttft', 'total']) {
    if (st[t] !== undefined) trends[`${t}_${requestClass}`].add(st[t]);
  }
  return st;
}

// A deterministic pseudo-random number generator (mulberry32) — the same schedule in every run.
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

export function summarize(name) {
  return function (data) {
    const file = `/results/${__ENV.RESULT || name}.json`;
    data.meta = { name: __ENV.RESULT || name, end: new Date().toISOString(), env: { APP_URL: APP } };
    return {
      [file]: JSON.stringify(data, null, 1),
      stdout: report_text(data),
    };
  };
}

// A concise console summary (no network dependencies): trends in ms, counters, rate, dropped_iterations.
function report_text(data) {
  const m = data.metrics;
  const lines = [`\n== ${data.meta.name} ==`];
  const duration_s = (data.state && data.state.testRunDurationMs || 0) / 1000;
  lines.push(`test duration: ${duration_s.toFixed(1)} s`);
  for (const [name, v] of Object.entries(m).sort()) {
    const val = v.values || {};
    if (v.type === 'trend' && val.count !== 0 && val['p(50)'] !== undefined) {
      lines.push(`${name.padEnd(36)} p50=${f(val['p(50)'])} p90=${f(val['p(90)'])} p99=${f(val['p(99)'])} max=${f(val.max)}`);
    } else if (v.type === 'counter' && val.count > 0) {
      lines.push(`${name.padEnd(36)} ${val.count} (${(val.rate || 0).toFixed(2)}/s)`);
    } else if (v.type === 'rate' && val.rate !== undefined) {
      lines.push(`${name.padEnd(36)} ${(val.rate * 100).toFixed(2)}%`);
    }
  }
  return lines.join('\n') + '\n';
}

function f(ms) {
  if (ms === undefined || ms === null) return '-';
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms.toFixed(0)}ms`;
}
