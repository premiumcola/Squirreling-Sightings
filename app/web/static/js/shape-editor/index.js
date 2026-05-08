// ─── shape-editor/index.js ─────────────────────────────────────────────────
// Public surface of the shape-editor package. Re-exports the names
// camedit/index.js consumes; importing this module also pulls in
// pointer.js for its side-effect IIFE that binds the canvas event
// listeners. The dependency graph is one-way:
//   index.js ─→ pointer.js ─→ ui.js ─→ canvas.js ─→ geometry.js
//                                  └→ persistence.js ─→ canvas.js
import './pointer.js';

export { drawShapes, getCanvasCtx } from './canvas.js';
export { loadMaskSnapshot, saveShapesIntoForm } from './persistence.js';
export { _renderShapeList, _updateShapeDrawingBar } from './ui.js';
