// ─── mediathek/bbox-overlay/_classfilter.js ────────────────────────────────
// "Which labels may paint on THIS recorded clip's overlay" — carved out of
// renderer.js so the class-visibility gate is its own small module,
// mirroring mediaview/live-detect-classfilter.js's shape (a camera-wide
// allow-list resolver + a combined visibility predicate).
//
// Layers TWO gates:
//   1. the CAMERA-wide allow-list (tracks.json's filter_applied, falling
//      back to the camera's live object_filter) + per-class hidden toggles
//      (hidden-classes.js) — unchanged from before this task.
//   2. NEW — the EVENT-wide triggering-class narrowing. "Bboxes: on" used
//      to mean "every class the camera's object_filter allows"; the actual
//      ask was "only the class that triggered THIS event". primaryLabel()
//      (core/primary-label.js, mirroring app/app/labels.py::primary_label())
//      is the one existing server-side notion of "the label an event counts
//      under" — reused here rather than inventing a fourth "which label
//      matters" predicate (see core/primary-label.js's own header for the
//      three that already existed and drifted).
//
// A motion-only event (primaryLabel falls back to MOTION_LABEL — no
// recognized object label at all) has no single triggering class to narrow
// to, so gate 2 is skipped and gate 1 alone still governs — this matters
// for clips where the offline tracking_worker's pass found object tracks
// the live alerting path never confirmed strongly enough to label.
import { state } from '../../core/state.js';
import { MOTION_LABEL, primaryLabel } from '../../core/primary-label.js';
import { lbState } from '../state.js';
import { _getHiddenClassesForCam } from './hidden-classes.js';

// Resolve the camera-config object_filter set, or null when unfiltered.
// tracks.json schema≥2 stores filter_applied at write time so this
// matches what the worker actually used; older sidecars + the legacy
// path fall back to the camera's live config.
export function _resolveAllowedLabels() {
  const tracks = lbState.item?._tracks;
  if (tracks && Array.isArray(tracks.filter_applied)) {
    return new Set(tracks.filter_applied);
  }
  const camId = lbState.item?.camera_id;
  if (camId) {
    const cam = (state.cameras || []).find((c) => (c.id || '') === camId);
    const of = cam?.object_filter;
    if (Array.isArray(of) && of.length > 0) {
      return new Set(of);
    }
  }
  return null;
}

// Combined visibility check — closure read once per render, called
// per track / per detection.
export function _makeLabelVisibleFn() {
  const allowed = _resolveAllowedLabels();
  const camId = lbState.item?.camera_id;
  const hidden = _getHiddenClassesForCam(camId);
  const trigger = primaryLabel(lbState.item?.labels);
  return (label) => {
    if (hidden.has(label)) return false;
    if (allowed !== null && !allowed.has(label)) return false;
    if (trigger !== MOTION_LABEL && label !== trigger) return false;
    return true;
  };
}
