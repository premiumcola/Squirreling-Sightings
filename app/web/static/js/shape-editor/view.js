// ─── shape-editor/view.js ──────────────────────────────────────────────────
// Where the frame sits on screen and how a finger maps onto it.
//
// Polygon coordinates live in FRAME units — the snapshot's natural pixels
// (640 × 360 on the substream). The canvas is something else entirely: it
// covers the snapshot PLUS a gutter on every side, at CSS size × device
// pixel ratio. Keeping the two apart is what the editor got wrong before:
//
//   * the canvas buffer WAS the 640 × 360 frame, stretched to 1000+ CSS
//     px on a desktop and to 2× DPR on a phone — every line and curve
//     came out blurry;
//   * the hit radius was 9 FRAME units, i.e. about 5 CSS px on a phone;
//   * the canvas ended exactly at the frame edge under a rounded,
//     overflow-clipped wrap, so a vertex on the edge was half outside
//     the touch surface and a corner vertex was under the rounding;
//   * nothing clamped a drag, so points left the frame (live data on
//     2026-10-19: x = 648 and y = −19 in a 640 × 360 zone).
//
// The pure functions below take a layout object and do arithmetic only;
// `currentLayout()` is the single place that reads the DOM.
import { byId } from '../core/dom.js';
import { shapeState } from '../core/state.js';

// Hit radius in CSS px, per pointer type. A fingertip covers ~10 mm; a
// mouse cursor is exact — the smaller radius keeps neighbouring
// handles separately clickable on a desktop.
export const HIT_CSS = { mouse: 10, pen: 12, touch: 22 };

// A point dropped or dragged within this many CSS px of a frame edge
// lands ON the edge. Without it a zone meant to cover the whole frame
// leaves a 2-px sliver at every border (the live zones top out at 636).
export const EDGE_SNAP_CSS = 8;

// Frame size used until a snapshot has loaded: the first polygon's own
// stamp if any carries one, else the 1280 × 720 authoring default
// shared with core/polygon-source.js.
export const DEFAULT_FRAME = { w: 1280, h: 720 };

export function fallbackFrame(polys) {
  for (const p of polys || []) {
    if (p && p.source_w > 0 && p.source_h > 0) return { w: p.source_w, h: p.source_h };
  }
  return { ...DEFAULT_FRAME };
}

// Layout = where the frame sits inside the canvas, in CSS px.
//   ox, oy  frame origin relative to the canvas' top-left corner
//   scale   CSS px per frame unit (uniform — the stage keeps the aspect)
//   w, h    frame size in frame units
export function frameLayout(canvasRect, stageRect, frame) {
  return {
    ox: stageRect.left - canvasRect.left,
    oy: stageRect.top - canvasRect.top,
    scale: stageRect.width / frame.w,
    w: frame.w,
    h: frame.h,
  };
}

export function toCss(layout, p) {
  return { x: layout.ox + p.x * layout.scale, y: layout.oy + p.y * layout.scale };
}

// CSS px relative to the canvas → frame units, NOT clamped. Hit tests
// use this one: a tap in the gutter next to an edge vertex must still
// reach that vertex.
export function toFrameRaw(layout, cssX, cssY) {
  return { x: (cssX - layout.ox) / layout.scale, y: (cssY - layout.oy) / layout.scale };
}

function _clampAxis(v, max, snap) {
  if (v <= snap) return 0;
  if (v >= max - snap) return max;
  return v;
}

// A position a point may actually take: inside the frame, snapped onto
// an edge when it is within EDGE_SNAP_CSS of one, rounded to whole
// frame units (what settings.json has always stored).
export function clampToFrame(layout, p, { snap = true } = {}) {
  const s = snap ? EDGE_SNAP_CSS / layout.scale : 0;
  return {
    x: Math.round(_clampAxis(p.x, layout.w, s)),
    y: Math.round(_clampAxis(p.y, layout.h, s)),
  };
}

export function hitRadius(layout, pointerType) {
  const css = HIT_CSS[pointerType] || HIT_CSS.mouse;
  return css / layout.scale;
}

// The bend handle sits ON the curve, at t = 0.5 — where geometry.js
// hit-tests it. Dragging it used to set the CONTROL point to the
// finger, so the curve's middle only travelled half as far as the
// finger, and bending a segment flush to the frame edge meant dragging
// the control point past the canvas, where the drag ended ("bleibt am
// Rand hängen"). Solving B(0.5) = m for the control point keeps the
// handle under the finger: B(0.5) = ¼·p0 + ½·cp + ¼·p1.
export function controlForMidpoint(p0, p1, m) {
  return {
    x: Math.round(2 * m.x - (p0.x + p1.x) / 2),
    y: Math.round(2 * m.y - (p0.y + p1.y) / 2),
  };
}

// Pull every vertex of a polygon back into its own stamped frame. Only
// polygons that carry a stamp are touched — a 1280-space polygon must
// not be clamped to a 640-space snapshot. Returns whether anything moved.
export function clampPolyToSource(poly) {
  if (!poly || typeof poly !== 'object' || Array.isArray(poly)) return false;
  const w = poly.source_w,
    h = poly.source_h;
  if (!(w > 0 && h > 0) || !Array.isArray(poly.points)) return false;
  let moved = false;
  for (const p of poly.points) {
    const x = Math.min(w, Math.max(0, p.x));
    const y = Math.min(h, Math.max(0, p.y));
    if (x !== p.x || y !== p.y) moved = true;
    p.x = x;
    p.y = y;
  }
  return moved;
}

// ── DOM side ────────────────────────────────────────────────────────────

export function currentFrame() {
  return (
    shapeState.frame || fallbackFrame([...(shapeState.zones || []), ...(shapeState.masks || [])])
  );
}

export function currentLayout() {
  const canvas = byId('maskCanvas');
  const stage = byId('maskStage');
  if (!canvas || !stage) return null;
  const cr = canvas.getBoundingClientRect();
  const sr = stage.getBoundingClientRect();
  if (!cr.width || !sr.width) return null; // tab hidden — nothing to map
  return { ...frameLayout(cr, sr, currentFrame()), cssW: cr.width, cssH: cr.height };
}

// Pointer event → {raw, at}: raw for hit tests, `at` for placement.
export function eventPoint(layout, evt) {
  const rect = byId('maskCanvas').getBoundingClientRect();
  const raw = toFrameRaw(layout, evt.clientX - rect.left, evt.clientY - rect.top);
  return { raw, at: clampToFrame(layout, raw) };
}
