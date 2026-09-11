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
// Three things are load-bearing in this file:
//   1. The relative-minute projection (_series) — the whole alignment.
//   2. The union minute domain that comes out of it: every episode keeps
//      its true duration relative to the others, „kein verzug des
//      zeitrahmens".
//   3. Several metrics at once, each on its own shared band. Which
//      metrics are on is _compare_metrics.js's business; why the Y axis
//      goes unlabelled the moment two units share the plot is
//      stats-chart/_multi_scale.js's.

import { esc } from '../core/dom.js';
import { renderEpisodeChart } from '../weather/stats-chart/_multi.js';
import { WEATHER_FIELD_LABEL_DE } from '../weather/stats.js';
import { STORM_METRIC_SHORT, slotColor, slotOf, slotRelease } from './_state.js';
import {
  classMeta,
  effectiveClass,
  episodeThresholds,
  episodeTitle,
  fmtDayMonth,
  fmtMetric,
  metricUnit,
  renderDeadEnd,
  thresholdFor,
} from './_helpers.js';
import { compareMetrics, metricPillsHtml, toggleCompareMetric } from './_compare_metrics.js';
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

// One series per (metric, episode) pair. Metric-major, so the chart's
// draw order groups a metric's curves together and the tooltip rows do
// the same.
//
// `label` is escaped HERE, at the source: it can be an operator-typed
// episode name and it lands in the tooltip as markup.
function _series(episodes, metrics) {
  const out = [];
  for (const metric of metrics) {
    for (const ep of episodes) {
      const slot = slotOf(ep.id);
      out.push({
        slot,
        colour: slotColor(slot),
        label: esc(episodeTitle(ep)),
        metric,
        points: _points(ep, metric),
      });
    }
  }
  return out;
}

// Legend chips: [1] ⚡ Hagelfront · 28.08. ✕ — the class is conveyed by
// the glyph, drawn monochrome in the SLOT colour, because in this view
// colour means episode and nothing else. Which METRIC a curve carries is
// never colour: it is the label drawn on the curve's own end.
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

/**
 * Every DISTINCT trigger level in the selection, per metric, as chart
 * lines.
 *
 * Each record stamps the thresholds it was measured against, and the
 * archive outlives the settings that produced it — so two episodes on
 * the same chart can legitimately have been judged against different
 * levels. Taking the first episode's value and drawing it across all
 * four curves labels three of them with a threshold that was never
 * theirs, which is why this returns a list: one line per level, with the
 * slot numbers in the label as soon as they disagree and the metric's
 * name as soon as more than one metric shares the plot (where an
 * unqualified "Schwelle" would be ambiguous across the bands).
 *
 * `thresholdFor` is what keeps a missing threshold missing: the payload
 * carries `null` for wind gusts (no event) and for visibility (fog is
 * configured as `vis_max_m`), and `Number(null)` is a finite 0 that
 * would otherwise paint a "Schwelle" line along the axis floor.
 */
export function metricThresholds(episodes, metrics) {
  const keys = Array.isArray(metrics) ? metrics : [metrics];
  const named = keys.length > 1;
  const out = [];
  for (const metric of keys) {
    const bySlot = new Map();
    for (const ep of episodes) {
      const v = thresholdFor(episodeThresholds(ep), metric);
      if (!Number.isFinite(v)) continue;
      bySlot.set(v, (bySlot.get(v) || []).concat(slotOf(ep.id)));
    }
    const levels = [...bySlot.entries()].sort((a, b) => a[0] - b[0]);
    const base = named ? `Schwelle ${STORM_METRIC_SHORT[metric] || metric}` : 'Schwelle';
    for (const [value, slots] of levels) {
      const label = levels.length < 2 ? base : `${base} ${slots.sort((a, b) => a - b).join('·')}`;
      out.push({ value, label, metric });
    }
  }
  return out;
}

// The axis hint doubles as the honesty notice. With one metric the Y
// axis is labelled in that metric's own unit and there is nothing to
// disclose; with several it is bare gridlines, and the reader has to be
// told in words where the numbers went and how to tell the curves apart.
function _hintHtml(metrics) {
  const base = 'Zeitachse relativ zum Höhepunkt · Messpunkt alle 15 min';
  if (metrics.length < 2) return `<div class="st-axis-hint">${base}</div>`;
  const names = metrics.map((k) => STORM_METRIC_SHORT[k] || k).join(' · ');
  return `<div class="st-axis-hint">${base}<br>${esc(names)} — eigene Skala je Messgröße,
    Kurven am Ende beschriftet, Werte im Tooltip</div>`;
}

function _shellHtml(episodes, metrics) {
  return `<div class="st-compare">
      <div class="st-dtop">
        <a class="st-back" href="#storms" aria-label="Zurück zur Liste">‹ Archiv</a>
        <span class="st-dwhen">${episodes.length} Gewitter im Vergleich</span>
      </div>
      ${_legendHtml(episodes)}
      ${metricPillsHtml(episodes, metrics)}
      <div class="ws-stats-chart-wrap st-chart-wrap" id="stormsCompareChart"></div>
      ${_hintHtml(metrics)}
      ${compareTableHtml(episodes, (id) => slotOf(id))}
    </div>`;
}

function _mountChart(host, episodes, metrics) {
  const wrap = host.querySelector('#stormsCompareChart');
  const names = metrics.map((k) => WEATHER_FIELD_LABEL_DE[k] || k).join(', ');
  renderEpisodeChart(wrap, _series(episodes, metrics), {
    metrics,
    unitOf: metricUnit,
    shortOf: (k) => STORM_METRIC_SHORT[k] || k,
    fmtValue: (v, metric) => fmtMetric(metric, v),
    thresholds: metricThresholds(episodes, metrics),
    aria: `Vergleich · ${names || 'keine Messgröße'}`,
  });
}

function _bind(host, episodes, onNavigate) {
  const rerender = () => renderCompare(host, episodes, onNavigate);
  host.querySelectorAll('[data-metric]').forEach((b) =>
    b.addEventListener('click', () => {
      toggleCompareMetric(episodes, b.dataset.metric);
      rerender();
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

export function renderCompare(host, episodes, onNavigate) {
  if (episodes.length < 2) {
    renderDeadEnd(host, 'Für einen Vergleich werden mindestens 2 Gewitter benötigt.', onNavigate);
    return;
  }
  // An empty list when no episode in the selection has a peak for ANY
  // metric. Passing an empty series renders the chart's own "keine
  // Messwerte" state, and no pill is marked active — never
  // selected-and-disabled.
  const metrics = compareMetrics(episodes);
  host.innerHTML = _shellHtml(episodes, metrics);
  _mountChart(host, episodes, metrics);
  _bind(host, episodes, onNavigate);
}
