// ─── shape-editor/hover.js ─────────────────────────────────────────────────
// Mouse-only hover feedback: which handle is under the cursor, and the
// cursor that says what a press would do. A finger has no hover, so
// pointer.js only calls hoverAt() for pointerType 'mouse'.
import { shapeState } from '../core/state.js';
import { _hitVertex, _hitMidpoint, _isClosingPoint } from './geometry.js';
import { hitRadius } from './view.js';
import { drawShapes } from './canvas.js';

function _cursorFor(vertex, mid, closing) {
  if (vertex) return 'move';
  if (mid) {
    const arr = mid.kind === 'zone' ? shapeState.zones : shapeState.masks;
    const curves = arr[mid.polyIdx] && arr[mid.polyIdx].curves;
    // Curved: "drag to reshape"; straight: "drag to bend".
    return Array.isArray(curves) && curves[mid.segIdx] ? 'move' : 'grab';
  }
  return closing ? 'pointer' : 'crosshair';
}

export function hoverAt(canvas, layout, raw) {
  const r = hitRadius(layout, 'mouse');
  const vertex = _hitVertex(raw, r);
  const mid = !vertex && !shapeState.points.length ? _hitMidpoint(raw, r) : null;
  const closing = !vertex && !mid && _isClosingPoint(raw, r);
  const sig = vertex
    ? `${vertex.kind}:${vertex.polyIdx}:${vertex.ptIdx}`
    : mid
      ? `m:${mid.kind}:${mid.polyIdx}:${mid.segIdx}`
      : closing
        ? 'close'
        : '';
  if (sig === shapeState.hoverSig) return;
  shapeState.hoverVertex = vertex;
  shapeState.hoverSig = sig;
  canvas.style.cursor = _cursorFor(vertex, mid, closing);
  drawShapes();
}

export function clearHover(canvas) {
  shapeState.hoverVertex = null;
  shapeState.hoverSig = '';
  canvas.style.cursor = 'crosshair';
  drawShapes();
}
