// ─── mediaview/canvas/bbox-layer.js ────────────────────────────────────────
// Bounding-box canvas-overlay renderer. Today this functionality lives
// in mediathek/bbox-overlay/renderer.js and raf.js; task #4 moves the
// implementation here and switches it to draw class-coloured strokes
// driven by core/icons.js (colors[label]).
//
// SKELETON — re-exports the existing implementation so consumers can
// migrate their imports without behaviour change.

export {
  _lbDrawDetections,
  _interpolateTrackAt,
  _resolveAllowedLabels,
} from '../../mediathek/bbox-overlay/renderer.js';
