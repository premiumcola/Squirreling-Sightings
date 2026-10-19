// ─── shape-editor/pointer.js ───────────────────────────────────────────────
// Pointer + toolbar event handlers. Importing this module binds them
// (side effect, see index.js). State machine:
//
//   pointerdown → grab vertex / bend handle (drag) | remember the tap
//   pointermove → move the grabbed handle          | mouse hover
//   pointerup   → save a moved drag                | tap closes / selects / adds
//
// Pointer Events with capture, not mouse + touch listeners: a drag used
// to end the moment the mouse left the canvas (mouseleave), which is
// where a handle being pulled toward the frame edge "got stuck". With
// capture the drag follows the pointer anywhere and the position is
// clamped to the frame instead.
import { byId } from '../core/dom.js';
import { shapeState } from '../core/state.js';
import { showToast, showConfirm } from '../core/toast.js';
import { _isClosingPoint, _findPolygonAt } from './geometry.js';
import { currentLayout, eventPoint, hitRadius } from './view.js';
import { grabAt, applyDrag, straightenAt } from './drag.js';
import { drawShapes } from './canvas.js';
import { saveShapesIntoForm, _nextPolyName } from './persistence.js';
import { _renderShapeList, _updateShapeDrawingBar } from './ui.js';
import { bindShapeModeToggle } from './mode-toggle.js';
import { hoverAt, clearHover } from './hover.js';

// A tap is a press that moved less than this many CSS px.
const TAP_SLOP_CSS = 4;
// Two taps this close in time and space are a double-tap. dblclick is
// mouse-only on iOS, so the touch double-tap is recognised here.
const DOUBLE_TAP_MS = 350;

let drag = null;
let down = null;
let lastTap = { at: 0, raw: null };

function _commitInProgressPolygon() {
  if (shapeState.points.length < 3) return false;
  // pn834 — stamp the polygon with the frame it was drawn in, so
  // zone-layer.js and mask_zones.py map it onto a main-stream clip of
  // any resolution. The frame is the snapshot's natural size, not the
  // canvas buffer (which is CSS size × device pixel ratio).
  const frame = shapeState.frame || { w: 1280, h: 720 };
  const poly = {
    points: [...shapeState.points],
    label: _nextPolyName(shapeState.mode),
    source_w: frame.w,
    source_h: frame.h,
  };
  if (shapeState.mode === 'zone') shapeState.zones.push(poly);
  else shapeState.masks.push(poly);
  shapeState.points = [];
  saveShapesIntoForm();
  drawShapes();
  _updateShapeDrawingBar();
  _renderShapeList();
  showToast(`${poly.label} gespeichert`, 'success');
  return true;
}

function _isDoubleTap(evt, layout, raw) {
  if (evt.pointerType !== 'touch') return false;
  const r = hitRadius(layout, 'touch');
  const prev = lastTap;
  lastTap = { at: Date.now(), raw };
  if (!prev.raw || lastTap.at - prev.at > DOUBLE_TAP_MS) return false;
  const near = (prev.raw.x - raw.x) ** 2 + (prev.raw.y - raw.y) ** 2 < r * r;
  if (near) lastTap = { at: 0, raw: null };
  return near;
}

function _straighten(layout, raw, pointerType) {
  if (!straightenAt(raw, hitRadius(layout, pointerType))) return false;
  saveShapesIntoForm();
  drawShapes();
  return true;
}

function onDown(evt) {
  if (!shapeState.camera || !evt.isPrimary) return;
  if (evt.pointerType === 'mouse' && evt.button !== 0) return;
  const layout = currentLayout();
  if (!layout) return;
  if (evt.cancelable) evt.preventDefault();
  const { raw, at } = eventPoint(layout, evt);
  if (_isDoubleTap(evt, layout, raw) && _straighten(layout, raw, 'touch')) return;
  try {
    evt.currentTarget.setPointerCapture(evt.pointerId);
  } catch {
    // capture is an improvement, not a requirement
  }
  drag = grabAt(raw, hitRadius(layout, evt.pointerType));
  down = { raw, at, clientX: evt.clientX, clientY: evt.clientY };
  if (drag && drag.mode === 'vertex') shapeState.hoverVertex = drag;
}

function onMove(evt) {
  if (!shapeState.camera || !evt.isPrimary) return;
  const layout = currentLayout();
  if (!layout) return;
  const { raw } = eventPoint(layout, evt);
  if (drag) {
    if (evt.cancelable) evt.preventDefault();
    applyDrag(drag, layout, raw);
    drawShapes();
    return;
  }
  if (evt.pointerType === 'mouse') hoverAt(evt.currentTarget, layout, raw);
}

function _endDrag() {
  if (drag && drag.moved) saveShapesIntoForm();
  drag = null;
  down = null;
}

function onUp(evt) {
  if (!shapeState.camera || !evt.isPrimary) return;
  if (drag) {
    _endDrag();
    if (evt.pointerType !== 'mouse') clearHover(evt.currentTarget);
    return;
  }
  const layout = currentLayout();
  if (!down || !layout) return;
  const moved = Math.hypot(evt.clientX - down.clientX, evt.clientY - down.clientY);
  const { raw, at } = down;
  down = null;
  if (moved > TAP_SLOP_CSS) return;
  if (evt.cancelable) evt.preventDefault();
  _tap(evt.currentTarget, layout, raw, at, evt.pointerType);
}

// While not drawing, a tap on a polygon SELECTS it and a tap on empty
// frame DESELECTS. New points are only added when nothing was selected
// and the tap missed every polygon. `at` is already clamped and edge-
// snapped: a tap in the gutter next to a corner puts the point exactly
// on that corner.
function _tap(canvas, layout, raw, at, pointerType) {
  if (_isClosingPoint(raw, hitRadius(layout, pointerType))) {
    _commitInProgressPolygon();
    clearHover(canvas);
    return;
  }
  if (shapeState.points.length === 0) {
    const hit = _findPolygonAt(at);
    if (hit) {
      const key = `${hit.kind}:${hit.idx}`;
      shapeState.pulse = key;
      shapeState.expandedRows.add(key);
      drawShapes();
      _renderShapeList();
      byId(`shapeRow_${hit.kind}_${hit.idx}`)?.scrollIntoView?.({
        behavior: 'smooth',
        block: 'nearest',
      });
      return;
    }
    if (shapeState.pulse) {
      shapeState.pulse = null;
      drawShapes();
      _renderShapeList();
      return;
    }
  }
  shapeState.points.push(at);
  drawShapes();
  _updateShapeDrawingBar();
}

function onDblClick(evt) {
  if (!shapeState.camera) return;
  const layout = currentLayout();
  if (!layout) return;
  if (_straighten(layout, eventPoint(layout, evt).raw, 'mouse') && evt.cancelable) {
    evt.preventDefault();
  }
}

function _bindToolbar() {
  byId('undoShapeBtn')?.addEventListener('click', () => {
    shapeState.points.pop();
    drawShapes();
    _updateShapeDrawingBar();
  });
  byId('saveShapeBtn')?.addEventListener('click', () => {
    if (shapeState.points.length < 3) {
      showToast('Mindestens 3 Punkte.', 'warn');
      return;
    }
    _commitInProgressPolygon();
  });
  byId('clearShapesBtn')?.addEventListener('click', async () => {
    if (!(await showConfirm('Alle Zonen und Masken löschen?'))) return;
    shapeState.zones = [];
    shapeState.masks = [];
    shapeState.points = [];
    shapeState.pulse = null;
    saveShapesIntoForm();
    drawShapes();
    _updateShapeDrawingBar();
    _renderShapeList();
  });
}

function _bindCanvas(canvas) {
  canvas.addEventListener('pointerdown', onDown);
  canvas.addEventListener('pointermove', onMove);
  canvas.addEventListener('pointerup', onUp);
  canvas.addEventListener('pointercancel', () => {
    _endDrag();
    clearHover(canvas);
  });
  canvas.addEventListener('pointerleave', () => {
    if (!drag) clearHover(canvas);
  });
  canvas.addEventListener('dblclick', onDblClick);
  // The canvas buffer follows the CSS size: a rotation, the panel
  // opening, or the tab becoming visible all need a redraw.
  if (typeof ResizeObserver !== 'undefined') {
    new ResizeObserver(() => drawShapes()).observe(canvas);
  }
}

(function _initShapeEditor() {
  const canvas = byId('maskCanvas');
  if (!canvas) return;
  // Idempotent — the binder guards with a dataset flag.
  bindShapeModeToggle();
  _bindCanvas(canvas);
  _bindToolbar();
  // persistence.loadMaskSnapshot sets the frame and redraws; the list
  // and the drawing bar follow here.
  byId('maskSnapshot')?.addEventListener('load', () => {
    _renderShapeList();
    _updateShapeDrawingBar();
  });
})();
