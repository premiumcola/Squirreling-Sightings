// ─── shape-editor/geometry.js ──────────────────────────────────────────────
// Pure-data accessors + polygon math + canvas-coordinate helpers. The
// only DOM touch is canvasPoint() reading the canvas bounding rect to
// translate pointer events; everything else is value-in / value-out.
import { byId } from '../core/dom.js';
import { shapeState } from '../core/state.js';

// Polygon shape: {points:[{x,y},...], label:"Zone 1"}. Raw arrays of
// points (legacy pre-label format) are still accepted — _polyPoints
// unwraps both shapes transparently.
export function _polyPoints(p){ return Array.isArray(p) ? p : (p?.points || []); }
export function _polyLabel(p, fallback){ return (p && p.label) || fallback; }
export function _polyLabels(p){
  if (!p || typeof p !== 'object') return [];
  return Array.isArray(p.labels) ? p.labels.slice() : [];
}

// Hit-test radius for vertex-grab and close-polygon detection. Shrunk
// from 12 to 9 after C1 — handles got smaller (radius 5 / 7), so the
// hit-test no longer needs to eat clicks well past the visible disc.
// Still touch-friendly: 9 source-resolution units typically resolve to
// ~25 CSS pixels at the mobile display size.
export const _SHAPE_HIT_PX = 9;

export function _hitVertex(pt){
  const test = (arr, kind) => {
    for (let i = arr.length - 1; i >= 0; i--){
      const pts = _polyPoints(arr[i]);
      for (let j = 0; j < pts.length; j++){
        const dx = pts[j].x - pt.x, dy = pts[j].y - pt.y;
        if (dx * dx + dy * dy <= _SHAPE_HIT_PX * _SHAPE_HIT_PX) return { kind, polyIdx: i, ptIdx: j };
      }
    }
    return null;
  };
  return test(shapeState.zones || [], 'zone') || test(shapeState.masks || [], 'mask');
}

export function _isClosingPoint(pt){
  if (!shapeState.points || shapeState.points.length < 3) return false;
  const first = shapeState.points[0];
  const dx = first.x - pt.x, dy = first.y - pt.y;
  return dx * dx + dy * dy <= _SHAPE_HIT_PX * _SHAPE_HIT_PX;
}

// Ray-casting point-in-polygon test against {x,y} polygon vertices.
export function _pointInPoly(pt, points){
  if (!Array.isArray(points) || points.length < 3) return false;
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++){
    const xi = points[i].x, yi = points[i].y;
    const xj = points[j].x, yj = points[j].y;
    const intersect = ((yi > pt.y) !== (yj > pt.y)) &&
                      (pt.x < (xj - xi) * (pt.y - yi) / ((yj - yi) || 1e-9) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

export function _findPolygonAt(pt){
  const test = (arr, kind) => {
    for (let i = arr.length - 1; i >= 0; i--){
      const pts = _polyPoints(arr[i]);
      if (_pointInPoly(pt, pts)) return { kind, idx: i };
    }
    return null;
  };
  return test(shapeState.zones || [], 'zone') || test(shapeState.masks || [], 'mask');
}

export function canvasPoint(evt){
  const canvas = byId('maskCanvas');
  const rect = canvas.getBoundingClientRect();
  // Support both mouse and touch events. Touch coords live on .touches
  // (move/start) or .changedTouches (end).
  const src = (evt.touches && evt.touches[0]) || (evt.changedTouches && evt.changedTouches[0]) || evt;
  const x = (src.clientX - rect.left) * (canvas.width / rect.width);
  const y = (src.clientY - rect.top) * (canvas.height / rect.height);
  return { x: Math.round(x), y: Math.round(y) };
}
