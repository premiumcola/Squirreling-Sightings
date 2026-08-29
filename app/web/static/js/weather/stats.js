// ─── weather/stats.js ──────────────────────────────────────────────────────
// Stage 24 of the legacy.js → ES modules refactor — Wetterstatistik
// chart + explainer + legend + pill bar + auto-refresh observer.
//
// R11 split: rendering now lives in focused sub-modules:
//   * stats-chart/         — SVG chart (paths, axes, hover tooltip)
//   * stats-thresholds.js  — threshold overlay (composed inside chart)
//   * stats-summary.js     — numeric chip strip + explainer card
//
// What stays here:
//   * shared state (_wsStatsState) + history fetch (loadWeatherStats)
//   * the orchestrator (renderWeatherStats) that drives all three renders
//   * pill-bar + IntersectionObserver lifecycle
//   * shared utilities used across modules (_wsFmtVal, palette, field
//     order, threshold/label/unit hints used by settings.js)
import { byId } from '../core/dom.js';
import { renderWeatherStatsChart } from './stats-chart/index.js';
import { renderWeatherStatsLegend, renderWeatherStatsExplainer } from './stats-summary.js';
import { apiGet } from '../core/api.js';

// ── Wetterdaten & Prognose chart (Phase 4) ──────────────────────────────────
// Single-source palette for the multi-line history chart. Re-uses the
// WEATHER_TYPES colours where the parameter maps cleanly onto an event
// type, picks close siblings for the diagnostic-only fields. Order here
// determines render order (last drawn sits on top).
export const WEATHER_STATS_PALETTE = {
  precipitation: '#5a8aa8', // matches heavy_rain
  snowfall: '#a8c0d4', // matches snow
  lightning_potential: '#facc15', // matches thunder badge
  visibility: '#94a3b8', // matches fog
  wind_gusts_10m: '#84cc16', // lime — diagnostic, distinct from the rain blues
  cloud_cover: '#a78bfa', // violet — diagnostic
  sun_altitude: '#fb923c', // matches sunset
};

export const _WS_FIELD_ORDER = [
  'precipitation',
  'snowfall',
  'lightning_potential',
  'visibility',
  'wind_gusts_10m',
  'cloud_cover',
  'sun_altitude',
];

let _wsStatsTimer_chart = null;
let _wsStatsObserver = null;
export const _wsStatsState = {
  hours: 24,
  // `hidden` is the source of truth for which curves are drawn — a
  // legend chip click toggles membership, independent of any other
  // chip ("mehrere an- und abwählen"). `isolated` is DERIVED, not set
  // directly: when hiding leaves exactly one field visible, the chart
  // switches to that field's real-value axis and the explainer card
  // follows it, same as the old single-isolate mode. Both are recomputed
  // in renderWeatherStats() before every render.
  hidden: new Set(),
  isolated: null,
  // Once the operator touches any chip, auto-hide stops recomputing —
  // otherwise re-enabling a flat field would just vanish again on the
  // next 60 s refresh.
  userAdjusted: false,
  data: null, // last fetched payload
  inFlight: false,
};

// A field with no non-null sample in the current window, or one that
// never moved (e.g. Schneefall pinned at 0.00 all day), earns nothing by
// being drawn — it just eats screen space and dilutes the curves that
// actually say something about this window. "Zeige nur relevante Werte,
// blende andere aus."
function _wsIsFlat(samples, key) {
  let lo = Infinity,
    hi = -Infinity,
    any = false;
  for (const s of samples) {
    const v = (s.values || {})[key];
    if (typeof v !== 'number' || !isFinite(v)) continue;
    any = true;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  return !any || hi - lo < 1e-9;
}

// How much a field's OWN window-relative swing earns it visual weight,
// as {width, opacity} for the SVG stroke. "Macht die Kurven kräftiger,
// die gerade interessant sind" — a field near its reference span (the
// same physical scales the storm archive scores intensity against, see
// weather_episodes/_consts.py INTENSITY_REFERENCE) renders bold; a flat
// stretch of the same field renders thin and dim instead of competing
// for attention with the line that is actually moving.
//
// cloud_cover / sun_altitude are excluded on purpose: both swing hugely
// on ANY ordinary day (sun altitude alone covers ~90°) without that
// swing meaning anything is "happening" — they render as fixed context
// lines instead of competing in the relevance ranking.
const _WS_EMPHASIS_REF_SPAN = {
  precipitation: 5, // mm/h
  snowfall: 1, // cm/h
  lightning_potential: 1, // J/kg — the corrected LPI trigger scale
  wind_gusts_10m: 30, // km/h
  visibility: 5000, // m
};
const _WS_CONTEXT_LINE = { width: 1.4, opacity: 0.55 };

export function wsLineEmphasis(key, lo, hi) {
  const ref = _WS_EMPHASIS_REF_SPAN[key];
  if (!ref) return _WS_CONTEXT_LINE;
  const t = Math.max(0, Math.min(1, Math.abs(hi - lo) / ref));
  return { width: 1.4 + t * 1.8, opacity: 0.55 + t * 0.45 };
}

export async function loadWeatherStats() {
  if (_wsStatsState.inFlight) return;
  _wsStatsState.inFlight = true;
  try {
    _wsStatsState.data = await apiGet('/api/weather/history?hours=' + _wsStatsState.hours);
    renderWeatherStats();
  } catch (_err) {
    /* leave the previous render up — single transient error shouldn't blank the chart */
  } finally {
    _wsStatsState.inFlight = false;
  }
}

// Decimal places per history field. The single source for it: the
// Gewitter-Archiv formats the same numbers in German notation and reads
// its banding from here, so a value cannot read as "12,4" in one panel
// and "12,40" in the other.
const _WS_INTEGER_FIELDS = new Set([
  'sun_altitude',
  'cloud_cover',
  'wind_gusts_10m',
  'visibility',
  'lightning_potential',
]);

export function wsFieldDigits(key) {
  return _WS_INTEGER_FIELDS.has(key) ? 0 : 2;
}

export function _wsFmtVal(key, v) {
  if (v == null || !isFinite(v)) return '—';
  const u = (_wsStatsState.data?.units || {})[key] || '';
  const s = v.toFixed(wsFieldDigits(key));
  return u ? s + ' ' + u : s;
}

// Fields currently drawn — every field in canonical order minus whatever
// is in `hidden`. Never empty: a chart with nothing on it is worse than
// one showing a field nobody asked for, so the legend refuses to hide
// the last remaining field (see renderWeatherStatsLegend).
export function wsVisibleFields() {
  return _WS_FIELD_ORDER.filter((k) => !_wsStatsState.hidden.has(k));
}

export function renderWeatherStats() {
  if (!_wsStatsState.userAdjusted) {
    const samples = _wsStatsState.data?.samples || [];
    const flat = new Set(_WS_FIELD_ORDER.filter((k) => _wsIsFlat(samples, k)));
    // Never auto-hide EVERY field (a brand-new install with an all-zero
    // window would otherwise blank the chart entirely).
    if (flat.size < _WS_FIELD_ORDER.length) _wsStatsState.hidden = flat;
  }
  const visible = wsVisibleFields();
  _wsStatsState.isolated = visible.length === 1 ? visible[0] : null;
  renderWeatherStatsChart();
  renderWeatherStatsLegend();
  renderWeatherStatsExplainer();
}

function _bindWeatherStatsPills() {
  const bar = byId('weatherStatsPills');
  if (!bar || bar.dataset.wired) return;
  bar.querySelectorAll('.ws-stats-pill').forEach((btn) => {
    btn.addEventListener('click', () => {
      const h = parseInt(btn.dataset.hours, 10) || 24;
      if (h === _wsStatsState.hours) return;
      _wsStatsState.hours = h;
      bar
        .querySelectorAll('.ws-stats-pill')
        .forEach((b) => b.classList.toggle('is-active', b === btn));
      loadWeatherStats();
    });
  });
  bar.dataset.wired = '1';
}

function _startWeatherStatsRefresh() {
  if (_wsStatsTimer_chart) return; // already running
  loadWeatherStats();
  _wsStatsTimer_chart = setInterval(loadWeatherStats, 60_000);
}

function _stopWeatherStatsRefresh() {
  if (_wsStatsTimer_chart) {
    clearInterval(_wsStatsTimer_chart);
    _wsStatsTimer_chart = null;
  }
}

function initWeatherStats() {
  const block = byId('weatherStatsBlock');
  if (!block) return;
  _bindWeatherStatsPills();
  if (_wsStatsObserver) return; // already initialised
  // Pause polling while the section is off-screen — the chart is a
  // dashboard for the Wetter section, not a background task.
  _wsStatsObserver = new IntersectionObserver(
    (entries) => {
      if (entries.some((e) => e.isIntersecting)) _startWeatherStatsRefresh();
      else _stopWeatherStatsRefresh();
    },
    { threshold: 0.05 },
  );
  _wsStatsObserver.observe(block);
}

// Per-type unit hint for the threshold slider in Settings → Ereignistypen.
// Exported so weather/settings.js can populate _renderWeatherEventsList +
// the per-event slider rows from a single source of truth.
export const WEATHER_THRESHOLD_HINTS = {
  thunder: { unit: 'J/kg', min: 0, max: 3000, step: 50, key: 'threshold' },
  heavy_rain: { unit: 'mm/h', min: 0, max: 30, step: 0.5, key: 'threshold' },
  snow: { unit: 'cm/h', min: 0, max: 5, step: 0.1, key: 'threshold' },
  fog: { unit: 'm', min: 100, max: 5000, step: 100, key: 'vis_max_m' },
  sunset: { unit: '°', min: -10, max: 15, step: 1, key: 'alt_max' },
};

export const WEATHER_FIELD_LABEL_DE = {
  precipitation: 'Niederschlag',
  snowfall: 'Schneefall',
  lightning_potential: 'Blitz-Potential',
  visibility: 'Sicht',
  wind_gusts_10m: 'Wind-Böen',
  cloud_cover: 'Bewölkung',
  weather_code: 'WMO-Code',
};
export const WEATHER_FIELD_UNIT_DE = {
  precipitation: 'mm/h',
  snowfall: 'cm/h',
  lightning_potential: 'J/kg',
  visibility: 'm',
  wind_gusts_10m: 'km/h',
  cloud_cover: '%',
  weather_code: '',
};

// Public surface is exposed via named exports below; legacy.js bridges
// initWeatherStats on window for loadAll().

export { initWeatherStats };

// Re-export render functions so existing consumers that import them by
// name from this module keep working without source changes.
export { renderWeatherStatsChart } from './stats-chart/index.js';
export { renderWeatherStatsLegend, renderWeatherStatsExplainer } from './stats-summary.js';

// ── window.* bridge ─────────────────────────────────────────────────────────
// loadAll() in live-update.js calls this by global name to wire the
// chart's IntersectionObserver + pill-bar listeners.
window.initWeatherStats = initWeatherStats;
