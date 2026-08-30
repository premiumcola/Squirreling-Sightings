// ─── mediaview/live-detect-classfilter.js ──────────────────────────────────
// "Is this class one this camera is even looking for?" — the single answer,
// shared by every live-detect renderer.
//
// The detector's label space is COCO's ~80 classes. A workshop bench, a
// garden chair and a parasol are reported on every tick, and drawing them
// buried the actual subject: plates stacked over the picture, and trails
// that connect two unrelated "bench" hits at opposite edges into a long
// white line straight across the frame.
//
// The camera's own `object_filter` is the source of truth — the Detections
// panel and the swimlane already gate on it (live-detect-panels.js:55-56,
// :216-217). This module exists so the bbox layer and the trail layer ask
// the same question in the same way instead of growing two near-identical
// predicates that drift.
//
// A camera with an EMPTY filter means "no restriction configured", not
// "show nothing" — that returns null and every label is kept.

import { state } from '../core/state.js';
import { S } from './live-detect-state.js';

/** The allowed label set for the camera currently under the simulator, or
 *  `null` when the camera restricts nothing. */
export function paintableLabels() {
  const cam = (state.cameras || []).find((c) => c.id === S.session?.camId) || {};
  const arr = Array.isArray(cam.object_filter) ? cam.object_filter : null;
  return arr && arr.length > 0 ? new Set(arr) : null;
}

/** Convenience predicate over `paintableLabels()`. Pass the set in when
 *  filtering a loop, so the camera lookup happens once per render rather
 *  than once per detection. */
export function keepsLabel(label, want) {
  const set = want === undefined ? paintableLabels() : want;
  return !set || set.has(label);
}
