// ─── mediaview/detail-pill.js ──────────────────────────────────────────────
// Absolute-positioned pill in the canvas bottom-left, hidden when no
// track is selected. Three mini-gauges:
//   Score   — fill = current score, fill colour = colors[label] when
//             ≥ threshold else amber; tick marker at the per-class
//             threshold from item.recording_settings.label_thresholds
//             (fallback: detection_min_score).
//   Höhe    — fill from last_bbox_frac_h, no tick.
//   Fläche  — fill from last_bbox_frac_area, no tick.
// Legend strip: "▍ Settings-Limit · ▪ Messwert".
//
// SKELETON — task #5 fills this in. Today the confidence-meter at
// bbox-overlay/confidence-meter.js does the closest equivalent (Score
// + Bbox-Höhe + Bbox-Fläche bars with thresholds); task #5 will lift
// its renderer into here and add the colours + legend strip.

export function renderDetailPill(/* host, trackContext */){}
