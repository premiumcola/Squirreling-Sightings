// ─── storms/_helpers.js ────────────────────────────────────────────────────
// Pure German formatters + the two derived facts the whole page reads
// from an episode record: its effective class and its Leitwert (the
// single peak that most exceeds its own configured threshold).

import { esc } from '../core/dom.js';
import { _wsStatsState, WEATHER_FIELD_UNIT_DE } from '../weather/stats.js';
import { STORM_CLASSES, STORM_METRICS } from './_state.js';

export { esc };

// Decimal places per metric — mirrors _wsFmtVal's banding so a value
// reads the same in the archive as it does in the Wetter panel.
const _DIGITS = {
  lightning_potential: 0,
  visibility: 0,
  wind_gusts_10m: 0,
  cloud_cover: 0,
  precipitation: 1,
  snowfall: 1,
};

export function fmtNumberDe(v, digits = 1) {
  if (v == null || !Number.isFinite(Number(v))) return '—';
  return Number(v).toLocaleString('de-DE', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** Value + unit in the metric's own unit, German decimal comma. */
export function fmtMetric(key, v) {
  if (v == null || !Number.isFinite(Number(v))) return '—';
  const unit = WEATHER_FIELD_UNIT_DE[key] || '';
  const s = fmtNumberDe(v, _DIGITS[key] ?? 1);
  return unit ? `${s} ${unit}` : s;
}

export function metricUnit(key) {
  return WEATHER_FIELD_UNIT_DE[key] || '';
}

const _p2 = (n) => (n < 10 ? '0' : '') + n;

function _date(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "28.08." — the list row's date. */
export function fmtDayMonth(iso) {
  const d = _date(iso);
  return d ? `${_p2(d.getDate())}.${_p2(d.getMonth() + 1)}.` : '—';
}

/** "28.08.2026" — the auto title's date. */
export function fmtDateFull(iso) {
  const d = _date(iso);
  return d ? `${_p2(d.getDate())}.${_p2(d.getMonth() + 1)}.${d.getFullYear()}` : '—';
}

/** "14:12" */
export function fmtTime(iso) {
  const d = _date(iso);
  return d ? `${_p2(d.getHours())}:${_p2(d.getMinutes())}` : '—';
}

export function fmtDuration(min) {
  const n = Number(min);
  return Number.isFinite(n) ? `${Math.round(n)} min` : '—';
}

/** "0,82" — German decimal comma, always two places. */
export function fmtIntensity(v) {
  return fmtNumberDe(v, 2);
}

export function episodeYear(ep) {
  const d = _date(ep?.started_at);
  return d ? d.getFullYear() : null;
}

/** user_class wins over the detector's auto_class. */
export function effectiveClass(ep) {
  return ep?.user_class || ep?.auto_class || null;
}

export function classMeta(cls) {
  return STORM_CLASSES[cls] || { de: cls || 'unbekannt', color: '#94a3b8', icon: '' };
}

/**
 * The row title. A named episode gets no extra "renamed" marker — the
 * name being non-generic IS the marker.
 */
export function episodeTitle(ep) {
  if (ep?.user_name) return ep.user_name;
  return `${classMeta(effectiveClass(ep)).de} · ${fmtDateFull(ep?.started_at)}`;
}

/**
 * Thresholds to measure this episode against. A snapshot stamped on the
 * record (backend §9.4) is the honest source; the live values the Wetter
 * panel above has almost always already fetched are the fallback. When
 * neither exists we simply have no threshold — callers draw no line and
 * no hint rather than inventing one.
 */
export function episodeThresholds(ep) {
  return ep?.thresholds || _wsStatsState.data?.thresholds || {};
}

/**
 * Leitwert — the single strongest peak, chosen as the peak with the
 * highest ratio to its OWN configured threshold. That is what makes
 * "2400 J/kg" and "12,4 mm/h" comparable at all. With no thresholds
 * configured anywhere we fall back to the first metric that has a peak,
 * in STORM_METRICS order, so the row still shows a number.
 */
export function leadPeak(ep) {
  const peaks = ep?.peaks || {};
  const thr = episodeThresholds(ep);
  let best = null;
  for (const key of STORM_METRICS) {
    const v = Number(peaks[key]);
    if (!Number.isFinite(v)) continue;
    const t = Number(thr[key]);
    const ratio = Number.isFinite(t) && t > 0 ? v / t : 0;
    if (!best || ratio > best.ratio) best = { key, value: v, ratio };
  }
  return best;
}

/**
 * Compare's default metric: the one whose peak most exceeds its own
 * threshold across the WHOLE selection. Deterministic, one expression,
 * and it opens on the thing that actually made these episodes storms.
 */
export function dominantMetric(episodes) {
  let best = null;
  for (const ep of episodes) {
    const lead = leadPeak(ep);
    if (!lead) continue;
    if (!best || lead.ratio > best.ratio) best = lead;
  }
  return best ? best.key : STORM_METRICS[0];
}

/** Metrics that are all-null across the selection → pill renders disabled. */
export function metricHasData(episodes, key) {
  return episodes.some((ep) => Number.isFinite(Number((ep?.peaks || {})[key])));
}
