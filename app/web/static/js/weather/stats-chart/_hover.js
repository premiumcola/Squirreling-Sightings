// ─── weather/stats-chart/_hover.js ─────────────────────────────────────────
// Hover tooltip — vertical guide line + floating box that lists every
// active line's value at the hovered timestamp. Pointer events cover
// mouse + touch + pen. Touch taps auto-hide after 2.5 s. Reduced-motion
// users get instant show/hide (the CSS .ws-chart-tooltip has no
// transition by default; this comment is the contract).
//
// This file is now the composition root of a three-module package; it
// crossed the 400-line ceiling at 404 and was cut along the section
// banner it already carried:
//
//   _hover_tip.js   the plain tooltip — sample lookup, guide, rows/head
//   _hover_drag.js  the additive drag-to-zoom + markMode pointer paths
//   _hover.js       the shared context + the single public entry point
//
// Imports run tip → drag → here, one direction only. Cutting the drag
// block out without that middle layer would have produced an import
// cycle, because _onDown calls the tooltip's _onMove and _onUp calls
// its _paintAt.
//
// The tooltip CONTENT is injectable (opts.head / opts.rows) so the storm
// compare chart can print "[1] Hagelfront · 2400 J/kg" per episode
// instead of one row per metric. Everything else — the x→sample lookup,
// the guide placement, the clamping, the touch auto-hide — is identical
// in both views and must stay one implementation.
//
// `opts.onRangeSelect` additively wires click-drag-to-zoom on top of the
// same pointer lifecycle: a drag past BRUSH_MIN_PX paints a translucent
// selection rect (`.ws-chart-brush`, present only in the Wetter panel's
// own SVG — see stats-chart/index.js) and fires
// `onRangeSelect(startTs, endTs)` with the RAW `ts` string of the
// nearest sample at each edge, never a re-derived Date().toISOString()
// (see weather/_zoom.js's docstring for why). Undefined `onRangeSelect`
// (every existing caller, including the storm compare chart) leaves this
// entirely inert — pointerdown still only paints the tooltip.
//
// `opts.markMode` + `opts.onMark` add a THIRD pointer behaviour —
// weather/_chart-annotations.js's data-anchored chart markers — mutually
// exclusive with drag-to-zoom (a truthy `markMode` skips starting a
// drag entirely; see _onDown). A tap (not a drag) inside the plot area
// resolves the nearest sample by time, same _xToTs/_nearestIdx snapping
// onRangeSelect uses, and hands the caller `(geo, idx, x, y)` where
// `geo` is the small explicit shape _chart-annotations.js's geometry
// functions share — this file stays unaware of what a "marker" even is,
// same decoupling `onRangeSelect` already has from weather/_zoom.js.
// `opts.ch` (chart height, injected by stats-chart/index.js's
// renderStatsChartInto — no other caller needs it) is what makes the
// vertical half of that geometry possible; every branch below that
// doesn't touch markMode ignores it entirely.

import { _onDown, _onDragMove, _onUp } from './_hover_drag.js';
import { _hide, _onMove } from './_hover_tip.js';

// Everything the pointer handlers need, resolved once at bind time.
// Returns null when the chart has no hover chrome to drive.
function _context(wrap, samples, fields, pad, cw, vbW, data, opts) {
  const svg = wrap.querySelector('svg');
  if (!svg) return null;
  const area = svg.querySelector('.ws-chart-hover-area');
  const guide = svg.querySelector('.ws-chart-guide');
  const tip = wrap.querySelector('.ws-chart-tooltip');
  if (!area || !guide || !tip) return null;
  // Absent for any chart that doesn't opt into brush chrome (the storm
  // compare chart's own SVG has none) — every brush helper below no-ops
  // when this is null.
  const brush = svg.querySelector('.ws-chart-brush');
  const dragStart = svg.querySelector('.ws-chart-drag-start');
  const dragEnd = svg.querySelector('.ws-chart-drag-end');
  const tFirst = new Date(samples[0]?.ts).getTime();
  const tLast = new Date(samples[samples.length - 1]?.ts).getTime();
  const first = new Date(tFirst);
  const last = new Date(tLast);
  return {
    wrap,
    svg,
    area,
    guide,
    tip,
    brush,
    dragStart,
    dragEnd,
    drag: null,
    markStart: null,
    samples,
    fields,
    pad,
    cw,
    // Chart height — only meaningful (and only ever set) when the caller
    // also wants markMode; see this file's own header comment.
    ch: Number.isFinite(opts.ch) ? opts.ch : null,
    vbW,
    opts,
    tFirst,
    tLast,
    tSpan: tLast - tFirst,
    labels: data?.labels_de || {},
    // Both halves of a tooltip row come from the payload this chart was
    // rendered with. `units` used to be missing, and the formatter fell
    // back to the Wetterdaten panel's module state — see _hover_tip.js.
    units: data?.units || {},
    hideTimer: { id: 0 },
    spansMultiDay:
      Number.isFinite(first.getTime()) &&
      Number.isFinite(last.getTime()) &&
      first.toDateString() !== last.toDateString(),
  };
}

export function bindChartHover(wrap, samples, fields, pad, cw, vbW, data, opts = {}) {
  const c = _context(wrap, samples, fields, pad, cw, vbW, data, opts);
  if (!c) return;
  const move = (ev) => {
    // While a drag is live, the drag guides/readout fully supersede the
    // plain hover crosshair — running both would draw the crosshair and
    // `.ws-chart-drag-end` on top of each other at the same x.
    if (c.drag) _onDragMove(c, ev);
    else _onMove(c, ev);
  };
  c.area.addEventListener('pointermove', move);
  c.area.addEventListener('pointerdown', (ev) => _onDown(c, ev));
  c.area.addEventListener('pointerup', (ev) => _onUp(c, ev));
  c.area.addEventListener('pointercancel', (ev) => _onUp(c, ev));
  c.area.addEventListener('pointerleave', () => {
    _hide(c);
    if (typeof opts.onGuide === 'function') opts.onGuide(null, -1);
  });
}
