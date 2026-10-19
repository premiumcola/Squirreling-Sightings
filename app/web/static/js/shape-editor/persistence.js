// ─── shape-editor/persistence.js ───────────────────────────────────────────
// Snapshot loading + form-field serialisation + polygon-name generation.
// loadMaskSnapshot owns the frame: the snapshot's natural size is the
// coordinate space every polygon is drawn and stamped in.
import { byId } from '../core/dom.js';
import { shapeState } from '../core/state.js';
import { drawShapes } from './canvas.js';
import { clampPolyToSource, fallbackFrame } from './view.js';

function _fitStage(frame) {
  const stage = byId('maskStage');
  if (stage) stage.style.aspectRatio = `${frame.w} / ${frame.h}`;
}

export function loadMaskSnapshot(camId) {
  if (!camId) return;
  const img = byId('maskSnapshot');
  if (!img) return;
  const polys = [...(shapeState.zones || []), ...(shapeState.masks || [])];
  // Points dragged out of the frame before drags were clamped (x = 648,
  // y = −19 in a 640 × 360 zone) sit outside the canvas, where nobody
  // can grab them. Pull them onto the edge; this lands in settings.json
  // only when the camera is saved.
  if (polys.map(clampPolyToSource).some(Boolean)) saveShapesIntoForm();
  shapeState.frame = null;
  shapeState.frameState = 'loading';
  img.hidden = false;
  img.onload = () => {
    shapeState.frame = { w: img.naturalWidth, h: img.naturalHeight };
    shapeState.frameState = 'ready';
    _fitStage(shapeState.frame);
    drawShapes();
  };
  // A failed load still leaves a usable surface: the stage keeps the
  // polygons' own aspect and the user can draw blind.
  img.onerror = () => {
    shapeState.frame = fallbackFrame(polys);
    shapeState.frameState = 'missing';
    img.hidden = true;
    _fitStage(shapeState.frame);
    drawShapes();
  };
  img.src = `/api/camera/${camId}/snapshot.jpg?t=${Date.now()}`;
}

export function saveShapesIntoForm() {
  const f = byId('cameraForm').elements;
  f['zones_json'].value = JSON.stringify(shapeState.zones || []);
  f['masks_json'].value = JSON.stringify(shapeState.masks || []);
}

export function _nextPolyName(kind) {
  const list = kind === 'zone' ? shapeState.zones || [] : shapeState.masks || [];
  const base = kind === 'zone' ? 'Zone' : 'Maske';
  const used = new Set();
  for (const p of list) {
    const lbl = (p && p.label) || '';
    const m = lbl.match(new RegExp('^' + base + '\\s+(\\d+)$', 'i'));
    if (m) used.add(parseInt(m[1], 10));
  }
  let n = 1;
  while (used.has(n)) n++;
  return `${base} ${n}`;
}
