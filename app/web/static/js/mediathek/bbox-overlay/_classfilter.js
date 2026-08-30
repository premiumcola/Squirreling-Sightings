// ─── mediathek/bbox-overlay/_classfilter.js ────────────────────────────────
// "Which labels may paint on THIS recorded clip's overlay" — carved out of
// renderer.js so the class-visibility gate is its own small module,
// mirroring mediaview/live-detect-classfilter.js's shape (a camera-wide
// allow-list resolver + a combined visibility predicate).
import { state } from '../../core/state.js';
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
  return (label) => {
    if (hidden.has(label)) return false;
    return allowed === null || allowed.has(label);
  };
}
