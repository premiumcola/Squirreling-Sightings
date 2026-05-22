// ─── shape-editor/persistence.js ───────────────────────────────────────────
// Snapshot loading + form-field serialisation + polygon-name generation.
// loadMaskSnapshot reaches into canvas.js for the redraw + fallback
// canvas — without that, a failed load would leave the user clicking
// into a 0×0 surface that swallows clicks.
import { byId } from '../core/dom.js';
import { shapeState } from '../core/state.js';
import { drawShapes, _maskCanvasFallback } from './canvas.js';

export function loadMaskSnapshot(camId) {
  if (!camId) return;
  const img = byId('maskSnapshot');
  if (!img) return;
  // Wire one-shot handlers so a failed load still leaves us with a
  // usable canvas instead of a 0×0 surface that swallows clicks.
  img.onload = () => {
    // A real snapshot is back — drop any aspect-ratio lock left
    // behind by a previous fallback render so the wrap follows the
    // image again.
    const wrap = byId('maskCanvas')?.parentElement;
    if (wrap) wrap.style.aspectRatio = '';
    drawShapes();
  };
  img.onerror = () => {
    _maskCanvasFallback();
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
