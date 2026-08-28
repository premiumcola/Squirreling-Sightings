// ─── storms/_compare.js ────────────────────────────────────────────────────
// Vergleich — Slot-Legende, Metrik-Pills, peak-aligned Overlay-Chart,
// Vergleichstabelle.
//
// The alignment rule and its rationale live in the chart module's
// docstring (weather/stats-chart/_multi.js) — t = 0 is each episode's
// peak_at, it is NOT configurable, and the reasoning is recorded there
// so a later refactor does not "helpfully" add wall-clock alignment
// back.
//
// Two things are load-bearing in this file:
//   1. The relative-minute projection (_series) — the whole alignment.
//   2. Exactly ONE metric at a time. Four episodes × seven metrics
//      cannot be overlaid; a shared absolute Y axis in the metric's own
//      unit is only possible because every line here is the same metric.

import { esc } from '../core/dom.js';
import { renderEpisodeChart } from '../weather/stats-chart/_multi.js';
import { WEATHER_FIELD_LABEL_DE } from '../weather/stats.js';
import {
  stormsState,
  STORM_METRICS,
  STORM_METRIC_SHORT,
  slotColor,
  slotOf,
  slotRelease,
} from './_state.js';
import {
  classMeta,
  dominantMetric,
  effectiveClass,
  episodeThresholds,
  episodeTitle,
  fmtDayMonth,
  fmtMetric,
  metricHasData,
  metricUnit,
  renderDeadEnd,
  thresholdFor,
} from './_helpers.js';
import { compareTableHtml } from './_compare_table.js';

/**
 * Project one episode's samples onto the peak-relative minute axis.
 * Returns [[relMinutes, value], …] — null values are kept so a gap in
 * the record splits the curve into separate runs instead of being
 * interpolated across.
 */
function _points(ep, metric) {
  const peak = Date.parse(ep.peak_at);
  if (!Number.isFinite(peak)) return [];
  const out = [];
  for (const s of ep.samples || []) {
    const t = Date.parse(s.ts);
    if (!Number.isFinite(t)) continue;
    const v = Number((s.values || {})[metric]);
    out.push([(t - peak) / 60_000, Number.isFinite(v) ? v : null]);
  }
  return out.sort((a, b) => a[0] - b[0]);
}

function _series(episodes, metric) {
  return episodes.map((ep) => ({
    slot: slotOf(ep.id),
    colour: slotColor(slotOf(ep.id)),
    label: episodeTitle(ep),
    points: _points(ep, metric),
  }));
}

// Legend chips: [1] ⚡ Hagelfront · 28.08. ✕ — the class is conveyed by
// the glyph, drawn monochrome in the SLOT colour, because in this view
// colour means episode and nothing else.
function _legendHtml(episodes) {
  return `<div class="st-legend-strip">${episodes
    .map((ep) => {
      const slot = slotOf(ep.id);
      const c = slotColor(slot);
      const m = classMeta(effectiveClass(ep));
      return `<span class="st-lchip" style="--sc:${c}">
          <span class="st-lslot">${slot}</span>
          <span class="st-lic" aria-hidden="true">${m.icon}</span>
          <span class="st-lname">${esc(episodeTitle(ep))} · ${esc(fmtDayMonth(ep.started_at))}</span>
          <button type="button" class="st-lx" data-drop="${esc(ep.id)}" aria-label="${esc(episodeTitle(ep))} aus dem Vergleich entfernen">✕</button>
        </span>`;
    })
    .join('')}</div>`;
}

// Metrics that are all-null across the selection render DISABLED —
// never silently absent, so the operator can see the metric exists and
// simply has no data here.
function _pillsHtml(episodes, active) {
  return `<div class="st-mpills" role="tablist" aria-label="Messgröße">${STORM_METRICS.map((k) => {
    const has = metricHasData(episodes, k);
    const full = WEATHER_FIELD_LABEL_DE[k] || k;
    return `<button type="button" class="st-mpill${k === active ? ' is-on' : ''}" data-metric="${esc(k)}"${has ? '' : ' disabled'} title="${esc(full)}" aria-label="${esc(full)}">${esc(STORM_METRIC_SHORT[k] || k)}</button>`;
  }).join('')}</div>`;
}

function _activeMetric(episodes) {
  const m = stormsState.metric;
  if (m && STORM_METRICS.includes(m) && metricHasData(episodes, m)) return m;
  return dominantMetric(episodes);
}

/**
 * The threshold for the metric, if any is known. Falls back to the live
 * Wetter-panel values; when neither exists we draw no line and no hint —
 * the chart is still correct without it.
 *
 * `thresholdFor` is what keeps a missing threshold missing: the payload
 * carries `null` for wind gusts (no event) and for visibility (fog is
 * configured as `vis_max_m`), and `Number(null)` is a finite 0 that
 * would otherwise paint a "Schwelle" line along the axis floor.
 */
export function metricThreshold(episodes, metric) {
  for (const ep of episodes) {
    const v = thresholdFor(episodeThresholds(ep), metric);
    if (Number.isFinite(v)) return v;
  }
  return NaN;
}

function _shellHtml(episodes, metric) {
  return `<div class="st-compare">
      <div class="st-dtop">
        <a class="st-back" href="#storms" aria-label="Zurück zur Liste">‹ Archiv</a>
        <span class="st-dwhen">${episodes.length} Gewitter im Vergleich</span>
      </div>
      ${_legendHtml(episodes)}
      ${_pillsHtml(episodes, metric)}
      <div class="ws-stats-chart-wrap st-chart-wrap" id="stormsCompareChart"></div>
      <div class="st-axis-hint">Zeitachse relativ zum Höhepunkt · Messpunkt alle 5 min</div>
      ${compareTableHtml(episodes, (id) => slotOf(id))}
    </div>`;
}

export function renderCompare(host, episodes, onNavigate) {
  if (episodes.length < 2) {
    renderDeadEnd(host, 'Für einen Vergleich werden mindestens 2 Gewitter benötigt.', onNavigate);
    return;
  }
  const metric = _activeMetric(episodes);
  host.innerHTML = _shellHtml(episodes, metric);
  const wrap = host.querySelector('#stormsCompareChart');
  renderEpisodeChart(wrap, _series(episodes, metric), {
    unit: metricUnit(metric),
    threshold: metricThreshold(episodes, metric),
    fmtValue: (v) => fmtMetric(metric, v),
    aria: `Vergleich · ${WEATHER_FIELD_LABEL_DE[metric] || metric}`,
  });
  host.querySelectorAll('[data-metric]').forEach((b) =>
    b.addEventListener('click', () => {
      stormsState.metric = b.dataset.metric;
      renderCompare(host, episodes, onNavigate);
    }),
  );
  host.querySelectorAll('[data-drop]').forEach((b) =>
    b.addEventListener('click', () => {
      const id = b.dataset.drop;
      slotRelease(id);
      const rest = episodes.filter((ep) => ep.id !== id);
      if (rest.length < 2) {
        onNavigate('#storms');
        return;
      }
      onNavigate(`#/gewitter/vergleich/${rest.map((ep) => ep.id).join(',')}`);
    }),
  );
}
