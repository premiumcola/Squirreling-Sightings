// ─── camedit/detection-perclass.js ─────────────────────────────────────────
// The confirmation-window save collector. Its render/bind counterparts
// (the step-3 per-class drilldown, the legacy #camConfirmGrid) were
// removed with D9 — the Erkennung tab now carries only the class
// filter, so there is no DOM source left to read a change FROM. This
// stays: it is the save collector's read of confirmation_window, and an
// absent camera dict still needs a `{}` fallback for a fresh camera.
//
// D2/D3 · the per-class confidence drilldown and its
// _collectLabelThresholds collector are GONE. They doubled the Netz,
// and the min="0.50" clamp on the sliders silently RAISED bird and
// squirrel from their shipped 0.45 the moment somebody opened the fold
// and pressed Speichern. The Netz writes label_thresholds now, one axis
// per class, and camedit echoes the stored map back untouched.

/** No UI writes this anymore (D9) — echo the stored value back
 *  untouched, exactly like label_thresholds above. Kept as its own
 *  function (rather than inlined at the one call site) so the "why"
 *  comment has somewhere to live next to the thing it explains. */
export function _collectConfirmationWindow(_form, existingCam) {
  return { ...(existingCam?.confirmation_window || {}) };
}
