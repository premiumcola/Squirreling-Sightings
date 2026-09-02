// ─── weather/stats-chart/_ticks.js ─────────────────────────────────────────
// Axis tick math + German label formatters. Pure functions, no DOM.

const WEEKDAY_DE = ['So.', 'Mo.', 'Di.', 'Mi.', 'Do.', 'Fr.', 'Sa.'];

// X-axis tick formatter — adapts to the configured window so the bottom
// of the chart communicates the actual time scale at a glance.
//   hours ≤ 24   → "HH:MM"
//   hours ≤ 168  → "Di. HH:MM"   (German weekday + time)
//   hours > 168  → "DD.MM."      (date only — month-scale window)
export function fmtTick(ts, hours) {
  if (!ts) return '';
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts.length >= 16 ? ts.slice(11, 16) : '';
  const p2 = (n) => (n < 10 ? '0' : '') + n;
  if (hours <= 24) {
    return p2(d.getHours()) + ':' + p2(d.getMinutes());
  }
  if (hours <= 168) {
    return WEEKDAY_DE[d.getDay()] + ' ' + p2(d.getHours()) + ':' + p2(d.getMinutes());
  }
  return p2(d.getDate()) + '.' + p2(d.getMonth() + 1) + '.';
}

// Round to a "nice number" — 1 / 2 / 5 × 10^n. round=true picks the
// nearest nice value (good for tick steps); round=false picks the
// next nice value ≥ input (good for axis bounds). Used by the
// Wetterstatistik chart for human-readable Y labels (0/5/10/15
// instead of 0.13/4.97/9.81/14.65).
function niceNum(value, round) {
  if (!Number.isFinite(value) || value <= 0) return 1;
  const exp = Math.floor(Math.log10(value));
  const f = value / Math.pow(10, exp);
  let nf;
  if (round) {
    if (f < 1.5) nf = 1;
    else if (f < 3) nf = 2;
    else if (f < 7) nf = 5;
    else nf = 10;
  } else {
    if (f <= 1) nf = 1;
    else if (f <= 2) nf = 2;
    else if (f <= 5) nf = 5;
    else nf = 10;
  }
  return nf * Math.pow(10, exp);
}

// Generate ~`target` evenly-spaced "nice" tick values across [lo, hi].
// Returns the tick array plus the snapped lo/hi so the caller can use
// the rounded bounds as the Y-axis baseline.
// How buildValueAxis prints one tick. Exported because stats-chart/
// _pad.js has to MEASURE the exact strings the axis is about to draw in
// order to size the left rail around them — a second formatter there
// would drift from this one and size the rail for a label that never
// renders.
export function fmtAxisValue(v) {
  return Number.isInteger(v) ? String(v) : v.toFixed(Math.abs(v) < 10 ? 1 : 0);
}

export function niceAxisTicks(lo, hi, target) {
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi - lo < 1e-9) {
    return { ticks: [lo], step: 1, niceLo: lo, niceHi: hi };
  }
  const range = niceNum(hi - lo, false);
  const step = niceNum(range / Math.max(1, target - 1), true);
  const niceLo = Math.floor(lo / step) * step;
  const niceHi = Math.ceil(hi / step) * step;
  const ticks = [];
  for (let v = niceLo; v <= niceHi + step / 2; v += step) ticks.push(v);
  return { ticks, step, niceLo, niceHi };
}

// Relative-minute X ticks — used by the storm compare chart, whose axis
// is "minutes before / after the episode's peak" rather than wall-clock.
// Same `cw / 90` density rule as buildXTicks so the two charts read at
// the same cadence. The sign is a real U+2212 minus, not a hyphen, so
// "−60′" doesn't look like a list bullet at 11 px.
export function fmtRelMinute(m) {
  const n = Math.round(m);
  if (n === 0) return '0';
  return (n < 0 ? '−' : '+') + Math.abs(n) + '′';
}

export function buildRelTicks({ minMin, maxMin, pad, cw, ch, vbH }) {
  const span = maxMin - minMin;
  if (!Number.isFinite(span) || span <= 0) return '';
  const target = Math.max(3, Math.min(8, Math.round(cw / 90)));
  const { ticks } = niceAxisTicks(minMin, maxMin, target);
  const baseY = (vbH - 8).toFixed(1);
  let svg = '';
  for (const v of ticks) {
    if (v < minMin || v > maxMin) continue;
    const x = pad.l + ((v - minMin) / span) * cw;
    svg += `<line x1="${x.toFixed(1)}" y1="${(pad.t + ch).toFixed(1)}" x2="${x.toFixed(1)}" y2="${(pad.t + ch + 5).toFixed(1)}" stroke="rgba(255,255,255,.12)" stroke-width="1"/>`;
    svg += `<text x="${x.toFixed(1)}" y="${baseY}" text-anchor="middle" font-size="11" fill="rgba(255,255,255,.55)">${fmtRelMinute(v)}</text>`;
  }
  return svg;
}

// Time-tick step ladder used by the chart's X-axis. Each entry is a
// candidate spacing in milliseconds; the picker snaps to the entry
// that gets the visible tick count closest to `target` for the
// current window. Covers 5 min through 1 year so a 24 h zoom shows
// 6 hourly ticks and a 6 mo zoom shows monthly ticks without a
// fixed if-else ladder.
const TIME_STEP_LADDER_MS = [
  5 * 60_000,
  10 * 60_000,
  15 * 60_000,
  30 * 60_000,
  60 * 60_000,
  2 * 60 * 60_000,
  3 * 60 * 60_000,
  6 * 60 * 60_000,
  12 * 60 * 60_000,
  24 * 60 * 60_000,
  2 * 24 * 60 * 60_000,
  7 * 24 * 60 * 60_000,
  14 * 24 * 60 * 60_000,
  30 * 24 * 60 * 60_000,
  90 * 24 * 60 * 60_000,
  180 * 24 * 60 * 60_000,
  365 * 24 * 60 * 60_000,
];

export function pickTimeStep(spanMs, target) {
  let best = TIME_STEP_LADDER_MS[0];
  let bestDiff = Infinity;
  for (const s of TIME_STEP_LADDER_MS) {
    const count = spanMs / s;
    if (count < 2) continue; // would yield <2 ticks → skip
    const diff = Math.abs(count - target);
    if (diff < bestDiff) {
      bestDiff = diff;
      best = s;
    }
  }
  return best;
}

// Snap a timestamp to the next "nice" boundary AT OR AFTER it,
// matching the step magnitude. Sub-day → round to the next hour;
// 1 d → midnight; ≥ 1 mo → start-of-month.
export function anchorTickStart(tFirst, stepMs) {
  const d = new Date(tFirst);
  if (stepMs < 24 * 60 * 60_000) {
    d.setMinutes(0, 0, 0);
    if (d.getTime() < tFirst) d.setHours(d.getHours() + 1);
    return d.getTime();
  }
  if (stepMs < 30 * 24 * 60 * 60_000) {
    d.setHours(0, 0, 0, 0);
    if (d.getTime() < tFirst) d.setDate(d.getDate() + 1);
    return d.getTime();
  }
  // Month-magnitude or larger: anchor at the 1st of the next month.
  d.setHours(0, 0, 0, 0);
  d.setDate(1);
  if (d.getTime() < tFirst) d.setMonth(d.getMonth() + 1);
  return d.getTime();
}

const MONTHS_DE = [
  'Jan',
  'Feb',
  'Mär',
  'Apr',
  'Mai',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Okt',
  'Nov',
  'Dez',
];

export function fmtTimeTick(t, stepMs) {
  const d = new Date(t);
  const p2 = (n) => (n < 10 ? '0' : '') + n;
  if (stepMs < 24 * 60 * 60_000) {
    return p2(d.getHours()) + ':' + p2(d.getMinutes());
  }
  if (stepMs < 60 * 24 * 60 * 60_000) {
    return p2(d.getDate()) + '. ' + MONTHS_DE[d.getMonth()];
  }
  return MONTHS_DE[d.getMonth()] + ' ' + String(d.getFullYear()).slice(-2);
}
