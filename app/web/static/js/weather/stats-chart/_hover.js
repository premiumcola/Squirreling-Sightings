// ─── weather/stats-chart/_hover.js ─────────────────────────────────────────
// Hover tooltip — vertical guide line + floating box that lists every
// active line's value at the hovered timestamp. Pointer events cover
// mouse + touch + pen. Touch taps auto-hide after 2.5 s. Reduced-motion
// users get instant show/hide (the CSS .ws-chart-tooltip has no
// transition by default; this comment is the contract).
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

import { WEATHER_STATS_PALETTE, _wsFmtVal } from '../stats.js';

// Default tooltip body: one row per active metric at this sample.
function _defaultRows(sample, fields, labels) {
  const sampleVals = sample.values || {};
  return fields
    .map((key) => {
      const v = sampleVals[key];
      if (v == null || !Number.isFinite(Number(v))) return '';
      const colour = WEATHER_STATS_PALETTE[key] || '#94a3b8';
      const lbl = labels[key] || key;
      const valFmt = _wsFmtVal(key, Number(v));
      return `<div class="ws-tt-row"><span class="ws-tt-dot" style="background:${colour}"></span><span class="ws-tt-lbl">${lbl}</span><span class="ws-tt-val">${valFmt}</span></div>`;
    })
    .filter(Boolean)
    .join('');
}

// Default tooltip header: HH:MM, with "· dd.MM" appended when the window
// spans more than one day so the same time-of-day isn't ambiguous.
function _defaultHead(sampleTs, spansMultiDay) {
  const p2 = (n) => (n < 10 ? '0' : '') + n;
  const dt = new Date(sampleTs);
  const headTime = `${p2(dt.getHours())}:${p2(dt.getMinutes())}`;
  if (!spansMultiDay) return headTime;
  return `${headTime} · ${p2(dt.getDate())}.${p2(dt.getMonth() + 1)}`;
}

// Position the tip 12 right / 6 above the cursor, clamped to the wrapper.
function _placeTip(tip, wrap, ev) {
  const wRect = wrap.getBoundingClientRect();
  const cx = ev.clientX - wRect.left + 12;
  const cy = ev.clientY - wRect.top - 6;
  tip.style.left = '0px';
  tip.style.top = '0px';
  const px = Math.max(4, Math.min(cx, wRect.width - tip.offsetWidth - 4));
  const py = Math.max(4, Math.min(cy, wRect.height - tip.offsetHeight - 4));
  tip.style.left = px + 'px';
  tip.style.top = py + 'px';
}

// Nearest sample index to timestamp `t`.
function _nearestIdx(samples, t) {
  let bestIdx = 0,
    bestDiff = Infinity;
  for (let i = 0; i < samples.length; i++) {
    const d = Math.abs(new Date(samples[i].ts).getTime() - t);
    if (d < bestDiff) {
      bestDiff = d;
      bestIdx = i;
    }
  }
  return bestIdx;
}

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
    hideTimer: { id: 0 },
    spansMultiDay:
      Number.isFinite(first.getTime()) &&
      Number.isFinite(last.getTime()) &&
      first.toDateString() !== last.toDateString(),
  };
}

function _hide(c) {
  c.tip.hidden = true;
  c.guide.style.display = 'none';
  if (c.hideTimer.id) {
    clearTimeout(c.hideTimer.id);
    c.hideTimer.id = 0;
  }
}

// Map the pointer's local x onto a sample, then paint guide + tooltip.
function _paintAt(c, localX, ev) {
  const t = c.tFirst + ((localX - c.pad.l) / c.cw) * c.tSpan;
  const idx = _nearestIdx(c.samples, t);
  const sample = c.samples[idx];
  const sampleTs = new Date(sample.ts).getTime();
  const guideX = c.pad.l + ((sampleTs - c.tFirst) / c.tSpan) * c.cw;
  c.guide.setAttribute('x1', guideX.toFixed(1));
  c.guide.setAttribute('x2', guideX.toFixed(1));
  c.guide.style.display = '';
  const head = c.opts.head ? c.opts.head(sample, idx) : _defaultHead(sampleTs, c.spansMultiDay);
  const rows = c.opts.rows ? c.opts.rows(sample, idx) : _defaultRows(sample, c.fields, c.labels);
  c.tip.innerHTML = `<div class="ws-tt-time">${head}</div>${rows}`;
  c.tip.hidden = false;
  _placeTip(c.tip, c.wrap, ev);
  if (typeof c.opts.onGuide === 'function') c.opts.onGuide(sample, idx);
}

// The pointer's local x in viewBox units. Shared by hover and brush so
// the "CSS transform on an ancestor / resize race" correction exists
// exactly once. `null` when the SVG isn't laid out yet.
function _localXOf(c, ev) {
  const rect = c.svg.getBoundingClientRect();
  if (rect.width === 0) return null;
  // The viewBox is authored at the wrapper's own CSS-pixel size, so this
  // ratio is normally 1. It stays a ratio rather than a plain
  // subtraction because a CSS transform on an ancestor (or a resize
  // landing between render and pointer event) would otherwise silently
  // offset every lookup.
  return (ev.clientX - rect.left) * (c.vbW / rect.width);
}

// Same correction as _localXOf, vertical axis — only used by the
// markMode tap handler (nothing else in this file needs a y position),
// so it silently returns null when `c.ch` was never supplied.
function _localYOf(c, ev) {
  if (c.ch === null) return null;
  const rect = c.svg.getBoundingClientRect();
  if (rect.height === 0) return null;
  const vbH = c.pad.t + c.ch + c.pad.b;
  return (ev.clientY - rect.top) * (vbH / rect.height);
}

function _onMove(c, ev) {
  if (!Number.isFinite(c.tFirst) || !Number.isFinite(c.tLast) || c.tSpan <= 0) {
    _hide(c);
    return;
  }
  const localX = _localXOf(c, ev);
  if (localX === null) return;
  if (localX < c.pad.l || localX > c.pad.l + c.cw) {
    _hide(c);
    return;
  }
  _paintAt(c, localX, ev);
  // Touch: auto-hide after 2.5 s of no further pointer events.
  if (ev.pointerType === 'touch') {
    if (c.hideTimer.id) clearTimeout(c.hideTimer.id);
    c.hideTimer.id = setTimeout(() => _hide(c), 2500);
  }
}

// ── Drag-to-zoom (opts.onRangeSelect) ───────────────────────────────────

// Below this pixel distance a press+release reads as a click/tap, not a
// drag — the operator must still be able to tap the chart for a
// tooltip without every tap firing a 0-width "zoom".
const BRUSH_MIN_PX = 8;

// Timestamp (ms, same numeric space as c.tFirst/c.tLast) at a clamped
// local-x. Clamping means a drag that overshoots the plot area still
// resolves to the nearest in-range edge instead of being lost.
function _xToTs(c, localX) {
  const x = Math.max(c.pad.l, Math.min(localX, c.pad.l + c.cw));
  return c.tFirst + ((x - c.pad.l) / c.cw) * c.tSpan;
}

function _paintBrushRect(c, x1, x2) {
  if (!c.brush) return;
  c.brush.setAttribute('x', Math.min(x1, x2).toFixed(1));
  c.brush.setAttribute('width', Math.abs(x2 - x1).toFixed(1));
  c.brush.style.display = '';
}

function _hideBrushRect(c) {
  if (c.brush) c.brush.style.display = 'none';
}

// Start/end edge guides — sibling lines to the plain hover `.ws-chart-
// guide`, painted only while a drag is in progress, so the operator can
// see exactly which two timestamps the drag currently spans BEFORE
// releasing ("die Endlinie müsste auch angezeichnet werden und am besten
// die Anfangslinie"). `x1`/`x2` are raw pointer x — always the visual
// drag start / current pointer position, regardless of drag direction.
function _paintDragGuides(c, x1, x2) {
  if (c.dragStart) {
    c.dragStart.setAttribute('x1', x1.toFixed(1));
    c.dragStart.setAttribute('x2', x1.toFixed(1));
    c.dragStart.style.display = '';
  }
  if (c.dragEnd) {
    c.dragEnd.setAttribute('x1', x2.toFixed(1));
    c.dragEnd.setAttribute('x2', x2.toFixed(1));
    c.dragEnd.style.display = '';
  }
}

function _hideDragGuides(c) {
  if (c.dragStart) c.dragStart.style.display = 'none';
  if (c.dragEnd) c.dragEnd.style.display = 'none';
}

// The tooltip, repurposed during a drag to show the two timestamps the
// current selection resolves to — same nearest-sample snap and the same
// `_defaultHead` formatting the plain hover tooltip and the eventual
// `onRangeSelect(startTs, endTs)` both use, so what the operator reads
// here while dragging is never a re-derived or differently-rounded
// value. Chronological order regardless of drag direction (right-to-left
// drags are common), matching how _onUp resolves start/end below.
function _paintDragTooltip(c, endX, ev) {
  const tA = _xToTs(c, c.drag.startX);
  const tB = _xToTs(c, endX);
  const idxLo = _nearestIdx(c.samples, Math.min(tA, tB));
  const idxHi = _nearestIdx(c.samples, Math.max(tA, tB));
  const tsLo = new Date(c.samples[idxLo].ts).getTime();
  const tsHi = new Date(c.samples[idxHi].ts).getTime();
  const headLo = _defaultHead(tsLo, c.spansMultiDay);
  const headHi = _defaultHead(tsHi, c.spansMultiDay);
  c.tip.innerHTML = `<div class="ws-tt-time">${headLo} → ${headHi}</div>`;
  c.tip.hidden = false;
  _placeTip(c.tip, c.wrap, ev);
}

function _onDown(c, ev) {
  _onMove(c, ev); // unchanged tap-shows-tooltip behaviour
  if (c.opts.markMode) {
    // Marking never starts a drag-to-zoom — the two are mutually
    // exclusive. Only track where the tap started; _onUp resolves
    // tap-vs-drag exactly like the brush below does.
    c.markStart = _localXOf(c, ev);
    return;
  }
  if (typeof c.opts.onRangeSelect !== 'function') return;
  if (!Number.isFinite(c.tFirst) || !Number.isFinite(c.tLast) || c.tSpan <= 0) return;
  const startX = _localXOf(c, ev);
  if (startX === null) return;
  c.drag = { startX };
  try {
    c.area.setPointerCapture(ev.pointerId);
  } catch {
    /* unsupported (old Safari) — release-outside-the-area still bubbles */
  }
}

function _onDragMove(c, ev) {
  if (!c.drag) return;
  const x = _localXOf(c, ev);
  if (x === null) return;
  _paintBrushRect(c, c.drag.startX, x);
  _paintDragGuides(c, c.drag.startX, x);
  // The drag readout replaces the plain value tooltip while dragging —
  // same element, repointed by _paintDragTooltip.
  _paintDragTooltip(c, x, ev);
}

// markMode's own tap-vs-drag resolution — same BRUSH_MIN_PX threshold
// the brush below uses, but a tap here means "place or remove a
// marker", never a range. A drag past the threshold reads as an
// accidental pan and produces no marker at all — marking never zooms.
function _onMarkUp(c, ev) {
  const x = _localXOf(c, ev);
  const startX = c.markStart;
  c.markStart = null;
  _hide(c); // the value tooltip from _onDown's _onMove must not fight the phase picker
  if (x === null || startX === null) return;
  if (Math.abs(x - startX) >= BRUSH_MIN_PX) return;
  if (x < c.pad.l || x > c.pad.l + c.cw) return;
  const y = _localYOf(c, ev);
  if (y === null || typeof c.opts.onMark !== 'function') return;
  const idx = _nearestIdx(c.samples, _xToTs(c, x));
  const geo = {
    samples: c.samples,
    fields: c.fields,
    pad: c.pad,
    cw: c.cw,
    ch: c.ch,
    tFirst: c.tFirst,
    tSpan: c.tSpan,
    wrap: c.wrap,
    svg: c.svg,
  };
  c.opts.onMark(geo, idx, x, y);
}

function _onUp(c, ev) {
  if (c.opts.markMode) {
    _onMarkUp(c, ev);
    return;
  }
  if (!c.drag) return;
  const x = _localXOf(c, ev);
  const { startX } = c.drag;
  c.drag = null;
  _hideBrushRect(c);
  _hideDragGuides(c);
  if (x === null || Math.abs(x - startX) < BRUSH_MIN_PX) {
    // A tap, not a drag — restore the plain value tooltip instead of
    // leaving the drag readout's stale "start → end" text on screen.
    if (x !== null) _paintAt(c, x, ev);
    else _hide(c);
    return;
  }
  const tA = _xToTs(c, startX);
  const tB = _xToTs(c, x);
  const idxA = _nearestIdx(c.samples, Math.min(tA, tB));
  const idxB = _nearestIdx(c.samples, Math.max(tA, tB));
  const startTs = c.samples[idxA].ts;
  const endTs = c.samples[idxB].ts;
  if (startTs === endTs) return; // snapped to the same sample — no real range
  c.opts.onRangeSelect(startTs, endTs);
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
