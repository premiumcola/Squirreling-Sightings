// ─── storms/_compare_metrics.js ────────────────────────────────────────────
// Which curves the compare view draws — the multi-select behind the
// Metrik-Pills, and the relevance rule that keeps „schnee im sommer" out
// of the way.
//
// Its own module rather than more lines in _compare.js: the selection is
// a state machine (sticky single metric → operator-owned set → the
// last-one-standing guard) with a rendering of its own, and _compare.js
// is already the composition root for the legend, the chart and the
// table.
//
// Nothing here decides how a curve LOOKS. That is the chart's business
// (weather/stats-chart/_multi_scale.js).

import { esc } from '../core/dom.js';
import { fieldDataExtent } from '../weather/stats-chart/_paths.js';
import { WEATHER_FIELD_LABEL_DE } from '../weather/stats.js';
import { stormsState, STORM_METRICS, STORM_METRIC_SHORT } from './_state.js';
import { dominantMetric, metricHasData } from './_helpers.js';

/**
 * Did this metric MOVE anywhere in the selection?
 *
 * „ich möchte bestimmte kurven als nicht relevant ausblenden können wie
 * z.B schnee im sommer" — a field pinned at 0.00 for the whole episode
 * draws a straight line along the floor, which costs a colour, a legend
 * entry and a tooltip row and says nothing.
 *
 * The honest primitive is fieldDataExtent (the raw min/max) and NOT
 * metricHasData, which only asks whether a PEAK was stamped, nor
 * fieldValueRange, which pins a flat line to a ±0.5 band so it can be
 * drawn mid-chart — that band reads back as a 1.0 swing that never
 * happened, and a dead-flat Schneefall curve looked like real snowfall
 * to exactly that mistake once already.
 *
 * A metric that moved in ONE episode counts as moving: the point of the
 * view is the difference between episodes, and "flat here, 4 cm/h
 * there" is the most interesting shape it can have.
 */
export function metricMoves(episodes, key) {
  return (episodes || []).some((ep) => {
    const extent = fieldDataExtent(ep?.samples || [], key);
    return !!extent && extent.hi - extent.lo > 1e-9;
  });
}

/**
 * The metrics currently drawn, in canonical STORM_METRICS order.
 *
 * Untouched (`metrics === null`) opens on exactly what this view always
 * opened on: the sticky single metric if this selection has data for it,
 * otherwise the dominant one. Multi-select is something the operator
 * does, never something the view does behind their back — four episodes
 * × five metrics is twenty curves, and nobody asked for that as a
 * landing state.
 *
 * Metrics with no data anywhere in the selection are filtered out on
 * every read, so changing which episodes are compared can never leave a
 * curve selected that has nothing to draw.
 */
export function compareMetrics(episodes) {
  const chosen = STORM_METRICS.filter(
    (k) => (stormsState.metrics || []).includes(k) && metricHasData(episodes, k),
  );
  if (chosen.length) return chosen;
  const sticky = stormsState.metric;
  if (sticky && STORM_METRICS.includes(sticky) && metricHasData(episodes, sticky)) return [sticky];
  const auto = dominantMetric(episodes);
  return auto ? [auto] : [];
}

/**
 * Toggle one metric on or off, returning the new active set.
 *
 * Two guards, both borrowed from the Wetterstatistik legend's chips:
 * turning off the last visible curve is a no-op rather than a blank
 * plot, and a metric with no data at all cannot be turned on.
 *
 * `stormsState.metric` is kept in step whenever the selection is back
 * down to one, so the cross-view stickiness the detail chart relies on
 * (open a storm after comparing rain, land on rain) still works.
 */
export function toggleCompareMetric(episodes, key) {
  if (!STORM_METRICS.includes(key) || !metricHasData(episodes, key))
    return compareMetrics(episodes);
  const active = new Set(compareMetrics(episodes));
  if (active.has(key)) {
    if (active.size <= 1) return [...active]; // last one standing
    active.delete(key);
  } else {
    active.add(key);
  }
  const next = STORM_METRICS.filter((k) => active.has(k));
  stormsState.metrics = next;
  if (next.length === 1) stormsState.metric = next[0];
  return next;
}

// Three pill states, and they are three because they mean three
// different things:
//
//   disabled — no data anywhere in the selection. Rendered, never
//              silently absent, so the operator can see the metric
//              exists and simply has nothing to say here.
//   is-flat  — has data but never moved across the whole selection
//              („schnee im sommer"). DIMMED, not disabled: still one
//              tap away, because "show me that it really is flat" is a
//              legitimate thing to ask. Same treatment the
//              Wetterstatistik legend gives an auto-hidden field.
//   is-on    — currently drawn.
function _pillHtml(episodes, key, active) {
  const has = metricHasData(episodes, key);
  const on = active.includes(key);
  const flat = has && !on && !metricMoves(episodes, key);
  const full = WEATHER_FIELD_LABEL_DE[key] || key;
  const hint = flat ? `${full} — bewegt sich in dieser Auswahl nicht` : full;
  let cls = 'st-mpill';
  if (on) cls += ' is-on';
  if (flat) cls += ' is-flat';
  return `<button type="button" class="${cls}" data-metric="${esc(key)}"${has ? '' : ' disabled'} aria-pressed="${on ? 'true' : 'false'}" title="${esc(hint)}" aria-label="${esc(hint)}">${esc(STORM_METRIC_SHORT[key] || key)}</button>`;
}

/**
 * The pill bar. `role="group"`, not `tablist`: these are independent
 * toggles now, and a tablist promises a screen reader exactly one
 * selected item.
 *
 * `is-multi` is unconditional here, not "once two are on" — the segment
 * well of a single-choice control is exactly the affordance that would
 * stop the operator ever trying a second pill. The detail view's own
 * pill bar keeps the segmented look, because there it really is one
 * choice.
 */
export function metricPillsHtml(episodes, active) {
  return `<div class="st-mpills is-multi" role="group" aria-label="Messgrößen — mehrere gleichzeitig möglich">${STORM_METRICS.map(
    (k) => _pillHtml(episodes, k, active),
  ).join('')}</div>`;
}
