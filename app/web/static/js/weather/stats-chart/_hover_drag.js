// ─── weather/stats-chart/_hover_drag.js ────────────────────────────────────
// The additive half of the chart pointer stack, split out of _hover.js:
// drag-to-zoom (`opts.onRangeSelect`) and data-anchored marking
// (`opts.markMode` + `opts.onMark`). Both ride the same pointer
// lifecycle the plain hover tooltip uses and both are inert unless the
// caller opts in, which is why they live behind their own module rather
// than inside the tooltip core.
//
// Imports flow one way — this file uses _hover_tip.js, never the other
// way round. _onDown deliberately calls the tooltip's _onMove first so a
// press still shows a value before any drag is recognised.

import {
  _defaultHead,
  _hide,
  _localXOf,
  _localYOf,
  _nearestIdx,
  _onMove,
  _paintAt,
  _placeTip,
} from './_hover_tip.js';

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

export function _onDown(c, ev) {
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

export function _onDragMove(c, ev) {
  if (!c.drag) return;
  const x = _localXOf(c, ev);
  if (x === null) return;
  _paintBrushRect(c, c.drag.startX, x);
  _paintDragGuides(c, c.drag.startX, x);
  // The drag readout replaces the plain value tooltip while dragging —
  // same element, repointed by _paintDragTooltip.
  _paintDragTooltip(c, x, ev);
}

// The two snapped sample indices a mark gesture resolves to.
// `[lo, hi]`, with `hi === null` for a tap (one sample, not a stretch).
function _markRange(c, startX, x, dragged) {
  const idxA = _nearestIdx(c.samples, _xToTs(c, dragged ? startX : x));
  const idxB = dragged ? _nearestIdx(c.samples, _xToTs(c, x)) : null;
  if (idxB == null) return [idxA, null];
  return [Math.min(idxA, idxB), Math.max(idxA, idxB)];
}

// markMode's own tap-vs-drag resolution, sharing the brush's own
// BRUSH_MIN_PX threshold. A TAP marks one sample. A DRAG along the curve
// marks the stretch between where it started and where it ended — "die
// Kurven so einzeln anklicken und dann die Bereiche markieren". A drag
// used to be discarded outright as an accidental pan, which is why the
// gesture the operator reached for did nothing at all. Marking still
// never zooms: the brush is not armed in this mode.
function _onMarkUp(c, ev) {
  const x = _localXOf(c, ev);
  const startX = c.markStart;
  c.markStart = null;
  _hide(c); // the value tooltip from _onDown's _onMove must not fight the phase picker
  if (x === null || startX === null) return;
  if (x < c.pad.l || x > c.pad.l + c.cw) return;
  const y = _localYOf(c, ev);
  if (y === null || typeof c.opts.onMark !== 'function') return;
  // Snap both ends to real samples, the same contract a point marker
  // has always had, and order them so a right-to-left drag is the same
  // range as a left-to-right one.
  const [lo, hi] = _markRange(c, startX, x, Math.abs(x - startX) >= BRUSH_MIN_PX);
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
  // The picker opens where the finger LEFT the curve, which for a drag
  // is the end the operator is still looking at.
  c.opts.onMark(geo, lo, x, y, hi);
}

export function _onUp(c, ev) {
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
