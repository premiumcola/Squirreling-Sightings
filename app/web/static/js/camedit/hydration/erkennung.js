// ─── camedit/hydration/erkennung.js ────────────────────────────────────────
// N17 · Pure-DOM hydrator for the Erkennung tab's form fields. D9 cut the
// tab down to the class filter alone — every field this hydrated moved
// either to the Fangnetz (netz/_tuning.js, its own GET /api/netz/state)
// or, for confirmation_window, lost its UI entirely (detection-perclass.js's
// _collectConfirmationWindow now just echoes the stored value back).
// `_state` is unused now that detection_min_score's fallback (the last
// reader of it) is gone with it — kept in the signature so callers
// don't all need updating for a parameter nothing else uses yet.

export function hydrateErkennungFields(formEl, c, _state) {
  const f = formEl.elements;
  if (f['bottom_crop_px']) f['bottom_crop_px'].value = c.bottom_crop_px || 0;
  // detection_trigger lives as a hidden input on the Erkennung tab during
  // this transition; the follow-up commit moves it to a visible select on
  // the Allgemein tab. Either way we set the value so save preserves it.
  if (f['detection_trigger'])
    f['detection_trigger'].value = c.detection_trigger || 'motion_and_objects';
}
