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
import { setZoomRange, clearZoomRange, isZoomActive } from './_zoom.js';
import { resetChartAnnotations } from './_chart-annotations.js';
import { applyRangeSlider, bindRangeSlider } from './_range-slider.js';
import { onTimeBindingRelease } from './_time-binding.js';

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
  // The one-shot latch for _autoPickRange. `hours` above is only a
  // starting guess until the first payload says how far the archive
  // actually goes back; after that the operator owns it.
  rangeAutoPicked: false,
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
  await _autoPickRange();
}

// First payload only: if the panel's window is wider than the archive
// can fill, drop to the widest one that has data and fetch that instead.
//
// Runs AFTER the inFlight guard has cleared, because it re-enters
// loadWeatherStats — doing it from inside renderWeatherStats (which runs
// while inFlight is still true) would silently no-op. One shot, whatever
// the outcome: the 60 s refresh must never drag the operator off a range
// they picked themselves, and neither must a later extent update.
async function _autoPickRange() {
  if (_wsStatsState.rangeAutoPicked) return;
  _wsStatsState.rangeAutoPicked = true;
  const want = applyRangeSlider(_wsStatsState.data?.extent, _wsStatsState.hours, isZoomActive());
  if (!Number.isFinite(want) || want === _wsStatsState.hours) return;
  _wsStatsState.hours = want;
  await loadWeatherStats();
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
  _renderWeatherRangeState();
}

// The slider's handle, its readout and the reset chip. The readout shows
// a step off _wsStatsState.hours ONLY while no custom drag-zoom is in
// effect — a dragged span matches no step on the ladder, so it reads
// „eigener Zeitraum" instead and the ✕ chip (the discoverable way back
// to a step) shows next to it.
function _renderWeatherRangeState() {
  const zoomed = isZoomActive();
  // How far the ladder reaches is recomputed here rather than once at
  // load, because the buffer grows under a panel that stays open and a
  // step that was out of reach at boot should become reachable on its
  // own.
  applyRangeSlider(_wsStatsState.data?.extent, _wsStatsState.hours, zoomed);
  const resetBtn = byId('weatherStatsZoomReset');
  if (resetBtn) resetBtn.hidden = !zoomed;
  const zoomActions = byId('weatherZoomActions');
  if (zoomActions) zoomActions.hidden = !zoomed;
}

// A fresh drag or an explicit reset invalidates whatever the save form
// (weather/_manual-event-save.js) was showing — it rebuilds itself from
// scratch on every "Als Ereignis speichern" click, so forcing it closed
// here is simpler than reaching across modules to refresh its contents
// in place. Plain DOM toggle, the two modules never need to know about
// each other beyond this shared element id — except chart-marking mode
// (weather/_chart-annotations.js), which MUST turn off in lockstep: a
// zoom change means the chart's samples are about to be a different
// window (or no zoom at all), and marking is only ever meaningful while
// the save panel showing THIS window is open. Resetting here — not only
// inside _manual-event-save.js's own close paths — covers every way the
// zoom can change out from under an open save panel (a preset click,
// the reset chip), not only the save form's own Abbrechen/Speichern.
function _closeZoomSavePanel() {
  const panel = byId('weatherZoomSavePanel');
  if (panel) panel.hidden = true;
  resetChartAnnotations();
}

// Fired by the chart's drag-to-zoom (stats-chart/_hover.js's
// opts.onRangeSelect, wired in stats-chart/index.js). Overrides whatever
// step the slider is on — no step on the ladder matches a dragged span.
// The zoom is the CHART'S and only the chart's. It used to narrow the
// Mediathek grid to the same window as well, and that coupling is gone
// root and branch: the grid sits in a different section of the page, so
// a span dragged down here left „Keine Einträge im gewählten Zeitraum"
// up there with nothing on screen to explain it. See
// library/_filter-state.js, and weather/_time-binding.js for the rule
// that now also drops the zoom itself once a filter up there is used.
export function onWeatherChartRangeSelect(startTs, endTs) {
  setZoomRange(startTs, endTs);
  renderWeatherStats();
  _closeZoomSavePanel();
}

// The reset chip, and moving the slider to ANY step (even the one it is
// already on) — both documented, discoverable ways back to a step on the
// ladder per the brief. Exported so weather.html's inline wiring (none
// currently) or a future affordance could call it directly; today the
// reset button, _bindWeatherRange below and the time-binding release
// subscriber at the foot of this file use it.
export function resetWeatherChartZoom() {
  clearZoomRange();
  // Closed (and mark-mode cleared) BEFORE the redraw below — unlike
  // onWeatherChartRangeSelect, this can fire while marking is active
  // (the reset chip isn't gated by the chart's own pointer mode), so the
  // very next render must already reflect markMode:false.
  _closeZoomSavePanel();
  renderWeatherStats();
}

function _bindWeatherRange() {
  // The extent is read at COMMIT time, not captured now: the buffer
  // grows under a panel that stays open, so the far end of the scale a
  // drag lands on must be the one that is reachable at that moment.
  bindRangeSlider(
    (h) => {
      const hadZoom = isZoomActive();
      // Settling the handle always clears a custom range, even when it
      // lands back on the step the panel was already showing — that's the
      // "picking a step again resets the zoom" affordance from the brief.
      clearZoomRange();
      if (hadZoom) _closeZoomSavePanel();
      if (h === _wsStatsState.hours) {
        if (hadZoom) renderWeatherStats();
        return;
      }
      _wsStatsState.hours = h;
      loadWeatherStats();
    },
    () => _wsStatsState.data?.extent,
  );
  const resetBtn = byId('weatherStatsZoomReset');
  if (resetBtn && !resetBtn.dataset.wired) {
    resetBtn.addEventListener('click', resetWeatherChartZoom);
    resetBtn.dataset.wired = '1';
  }
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
  _bindWeatherRange();
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
  sun_altitude: 'Sonnenhöhe',
  weather_code: 'WMO-Code',
};
export const WEATHER_FIELD_UNIT_DE = {
  precipitation: 'mm/h',
  snowfall: 'cm/h',
  lightning_potential: 'J/kg',
  visibility: 'm',
  wind_gusts_10m: 'km/h',
  cloud_cover: '%',
  sun_altitude: '°',
  weather_code: '',
};

// Public surface is exposed via named exports below; legacy.js bridges
// initWeatherStats on window for loadAll().

export { initWeatherStats };

// Re-export render functions so existing consumers that import them by
// name from this module keep working without source changes.
export { renderWeatherStatsChart } from './stats-chart/index.js';
export { renderWeatherStatsLegend, renderWeatherStatsExplainer } from './stats-summary.js';

// The time chooser only ever narrows while it is the last thing the
// operator touched — a class / species / camera / library-chip filter up
// the page releases it (weather/_time-binding.js owns that rule). The
// release is a pure state change over in _zoom.js; redrawing the chart
// at full range, and closing a save panel that was describing the window
// just dropped, is this module's half of it. Registered at module scope
// rather than in initWeatherStats() so a release that lands before the
// section has ever scrolled into view still leaves the chart honest.
onTimeBindingRelease(() => {
  _closeZoomSavePanel();
  renderWeatherStats();
});

// ── window.* bridge ─────────────────────────────────────────────────────────
// loadAll() in live-update.js calls this by global name to wire the
// chart's IntersectionObserver + range-slider listeners.
window.initWeatherStats = initWeatherStats;
