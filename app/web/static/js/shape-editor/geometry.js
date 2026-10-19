// ─── shape-editor/geometry.js ──────────────────────────────────────────────
// Pure-data accessors + polygon math, all in frame units. Mapping
// between the screen and the frame lives in view.js.
import { shapeState } from '../core/state.js';

// Polygon shape: {points:[{x,y},...], label:"Zone 1"}. Raw arrays of
// points (legacy pre-label format) are still accepted — _polyPoints
// unwraps both shapes transparently.
export function _polyPoints(p) {
  return Array.isArray(p) ? p : p?.points || [];
}
export function _polyLabel(p, fallback) {
  return (p && p.label) || fallback;
}
export function _polyLabels(p) {
  if (!p || typeof p !== 'object') return [];
  return Array.isArray(p.labels) ? p.labels.slice() : [];
}
// C2 — per-segment curve control points. curves[i] is the quadratic
// bezier control point for the segment from points[i] to
// points[(i+1) % N], or null/undefined for a straight segment.
// Legacy polygons (no curves key) → empty array → every segment is
// drawn straight. The schema lives only in storage/settings.json under
// the polygon's "curves" key; nothing on disk changes for polygons
// the user hasn't bent.
export function _polyCurves(p) {
  if (!p || typeof p !== 'object' || Array.isArray(p)) return [];
  return Array.isArray(p.curves) ? p.curves : [];
}

// The visual middle of segment i: the chord midpoint for a straight
// segment, the quadratic bezier at t = 0.5 for a curved one
// (0.25·p0 + 0.5·cp + 0.25·p1). The bend handle is drawn and hit-tested
// here, and view.controlForMidpoint inverts it while dragging.
export function segmentMidpoint(p0, p1, cp) {
  if (cp && Number.isFinite(cp.x) && Number.isFinite(cp.y)) {
    return { x: 0.25 * p0.x + 0.5 * cp.x + 0.25 * p1.x, y: 0.25 * p0.y + 0.5 * cp.y + 0.25 * p1.y };
  }
  return { x: (p0.x + p1.x) / 2, y: (p0.y + p1.y) / 2 };
}

const _near = (a, b, r) => (a.x - b.x) ** 2 + (a.y - b.y) ** 2 <= r * r;

// Hit tests take the radius in FRAME units from the caller —
// view.hitRadius() derives it from CSS px and the pointer type, so a
// finger gets a fingertip and a mouse gets a cursor.
export function _hitVertex(pt, r) {
  const test = (arr, kind) => {
    for (let i = arr.length - 1; i >= 0; i--) {
      const pts = _polyPoints(arr[i]);
      for (let j = 0; j < pts.length; j++) {
        if (_near(pts[j], pt, r)) return { kind, polyIdx: i, ptIdx: j };
      }
    }
    return null;
  };
  return test(shapeState.zones || [], 'zone') || test(shapeState.masks || [], 'mask');
}

// Vertex hits take priority over midpoint hits in pointer.js, so a
// vertex wins where handles overlap (it is drawn on top).
export function _hitMidpoint(pt, r) {
  const test = (arr, kind) => {
    for (let i = arr.length - 1; i >= 0; i--) {
      const pts = _polyPoints(arr[i]);
      if (pts.length < 2) continue;
      const curves = _polyCurves(arr[i]);
      for (let s = 0; s < pts.length; s++) {
        const m = segmentMidpoint(pts[s], pts[(s + 1) % pts.length], curves[s]);
        if (_near(m, pt, r)) return { kind, polyIdx: i, segIdx: s };
      }
    }
    return null;
  };
  return test(shapeState.zones || [], 'zone') || test(shapeState.masks || [], 'mask');
}

export function _isClosingPoint(pt, r) {
  if (!shapeState.points || shapeState.points.length < 3) return false;
  return _near(shapeState.points[0], pt, r);
}

// Ray-casting point-in-polygon test against {x,y} polygon vertices.
export function _pointInPoly(pt, points) {
  if (!Array.isArray(points) || points.length < 3) return false;
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const xi = points[i].x,
      yi = points[i].y;
    const xj = points[j].x,
      yj = points[j].y;
    const intersect =
      yi > pt.y !== yj > pt.y && pt.x < ((xj - xi) * (pt.y - yi)) / (yj - yi || 1e-9) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

export function _findPolygonAt(pt) {
  const test = (arr, kind) => {
    for (let i = arr.length - 1; i >= 0; i--) {
      const pts = _polyPoints(arr[i]);
      if (_pointInPoly(pt, pts)) return { kind, idx: i };
    }
    return null;
  };
  return test(shapeState.zones || [], 'zone') || test(shapeState.masks || [], 'mask');
}
