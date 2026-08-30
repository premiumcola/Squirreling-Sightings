// ─── core/primary-label.js ──────────────────────────────────────────────────
// Bit-for-bit mirror of app/app/labels.py's OBJECT_LABELS + primary_label()
// — the ONE label bucket an event is counted / triggered under. The first
// entry in the event's OWN `labels` array that is a recognized object label
// wins; everything else (an empty list, a bare ["motion"], or a label this
// build has never heard of) falls back to MOTION_LABEL.
//
// Before this module, "which label matters" had three independent, drifting
// answers: mediathek/orchestration.js's `_badgeLabel` picked "first non-
// motion label" (equivalent to this ONLY as long as item.labels never
// carries an unrecognized label), live-detect-classfilter.js's
// paintableLabels/keepsLabel answer a different question (camera-wide
// allow-list, not per-event trigger), and the recorded bbox overlay had no
// notion of "triggering label" at all. Both orchestration.js and
// mediathek/bbox-overlay/_classfilter.js now import this.
export const OBJECT_LABELS = [
  'person',
  'cat',
  'bird',
  'car',
  'dog',
  'squirrel',
  'fox',
  'hedgehog',
  'marten',
  'deer',
];

export const MOTION_LABEL = 'motion';

/**
 * The single bucket an event is counted under. Mirrors labels.py's
 * primary_label(): the first entry in `labels` that is a recognized
 * object label wins; everything else falls back to MOTION_LABEL.
 */
export function primaryLabel(labels) {
  for (const label of labels || []) {
    if (label && OBJECT_LABELS.includes(label)) return label;
  }
  return MOTION_LABEL;
}
