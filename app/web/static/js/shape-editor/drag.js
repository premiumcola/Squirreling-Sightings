// ─── shape-editor/drag.js ──────────────────────────────────────────────────
// Grabbing and moving a vertex or a bend handle. Frame units throughout;
// the caller passes the layout so clamping and snapping know the scale.
//
// The grab keeps the offset between finger and handle. With a 22-px
// touch radius the finger rarely lands on the handle's centre, and
// snapping the handle to the finger made every touch-drag start with a
// jump.
import { shapeState } from '../core/state.js';
import { _hitVertex, _hitMidpoint, _polyPoints, _polyCurves, segmentMidpoint } from './geometry.js';
import { clampToFrame, controlForMidpoint } from './view.js';

const _list = (kind) => (kind === 'zone' ? shapeState.zones : shapeState.masks);

export function dragPoly(drag) {
  return _list(drag.kind)[drag.polyIdx];
}

// While a new polygon is being placed, every tap drops the next vertex,
// so bend handles stop answering — only existing vertices stay grabbable.
export function grabAt(raw, r) {
  const hit = _hitVertex(raw, r);
  if (hit) {
    const p = _polyPoints(_list(hit.kind)[hit.polyIdx])[hit.ptIdx];
    return { ...hit, mode: 'vertex', dx: p.x - raw.x, dy: p.y - raw.y, moved: false };
  }
  if (shapeState.points.length) return null;
  const mid = _hitMidpoint(raw, r);
  if (!mid) return null;
  const poly = _list(mid.kind)[mid.polyIdx];
  const pts = _polyPoints(poly);
  const m = segmentMidpoint(
    pts[mid.segIdx],
    pts[(mid.segIdx + 1) % pts.length],
    _polyCurves(poly)[mid.segIdx],
  );
  return { ...mid, mode: 'midpoint', dx: m.x - raw.x, dy: m.y - raw.y, moved: false };
}

// Vertices are clamped into the frame and snapped onto an edge near it.
// A bend handle is clamped too, but not snapped — and because it stays
// ON the curve, a segment can now be bent flush against the frame edge
// with the finger still inside the frame.
export function applyDrag(drag, layout, raw) {
  const poly = dragPoly(drag);
  const pts = _polyPoints(poly);
  if (!pts.length) return;
  const target = { x: raw.x + drag.dx, y: raw.y + drag.dy };
  if (drag.mode === 'vertex') {
    const at = clampToFrame(layout, target);
    pts[drag.ptIdx].x = at.x;
    pts[drag.ptIdx].y = at.y;
  } else {
    const m = clampToFrame(layout, target, { snap: false });
    if (!Array.isArray(poly.curves)) poly.curves = new Array(pts.length).fill(null);
    const p0 = pts[drag.segIdx];
    const p1 = pts[(drag.segIdx + 1) % pts.length];
    poly.curves[drag.segIdx] = controlForMidpoint(p0, p1, m);
  }
  drag.moved = true;
}

// Double-click / double-tap on a curved segment's handle straightens
// it. Once every segment is straight again the key goes away, so
// settings.json diffs for never-bent polygons stay clean.
export function straightenAt(raw, r) {
  if (shapeState.points.length) return false;
  const hit = _hitMidpoint(raw, r);
  if (!hit) return false;
  const poly = _list(hit.kind)[hit.polyIdx];
  if (!poly || !Array.isArray(poly.curves) || !poly.curves[hit.segIdx]) return false;
  poly.curves[hit.segIdx] = null;
  if (poly.curves.every((c) => c == null)) delete poly.curves;
  return true;
}
