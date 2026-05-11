// ─── mediaview/playbar/swimlane.js ─────────────────────────────────────────
// Per-class swimlane row builder. Each row prefixes a class icon
// (OBJ_SVG[label] from core/icons.js) + class label (OBJ_LABEL[label])
// + class-coloured track bars (colors[label]). Track-loss × marker
// keeps its current tooltip behaviour.
//
// SKELETON — re-exports the existing timeline-panel implementation;
// task #4 will lift it here and re-style with the class-coloured fills.

export {
  lbClearTrackTimeline,
  lbRenderTrackTimeline,
} from '../../mediathek/bbox-overlay/timeline-panel.js';
