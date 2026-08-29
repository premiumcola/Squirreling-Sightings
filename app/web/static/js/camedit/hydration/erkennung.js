// ─── camedit/hydration/erkennung.js ────────────────────────────────────────
// N17 · Pure-DOM hydrator for the Erkennung tab's form fields. Carved
// out of editCamera() in camedit/index.js so the orchestration body
// shrinks without changing observable behaviour. Every field set here
// was previously set inline in the same order; the function is called
// in exactly the same slot of editCamera so state-dependent siblings
// (drilldowns) still see populated values when they run.
//
// The scan-speed/motion/tracking/ROI fields this used to hydrate moved
// to the Netz page's Kamera-Feinschliff fold (netz/_tuning.js), which
// reads its own state from GET /api/netz/state instead of this form.
// `_state` is unused now that detection_min_score's fallback (the last
// reader of it) is gone with it — kept in the signature so callers
// don't all need updating for a parameter nothing else uses yet.

export function hydrateErkennungFields(formEl, c, _state) {
  const f = formEl.elements;
  if (f['bottom_crop_px']) f['bottom_crop_px'].value = c.bottom_crop_px || 0;
  // Confirmation-window step 3 sliders — confirm_n/confirm_seconds carry
  // the new global entry. Existing per-class entries (cw[person] etc.)
  // stay in storage untouched.
  if (f['confirm_n']) {
    const g = (c.confirmation_window || {}).global || {};
    const n = parseInt(g.n, 10);
    f['confirm_n'].value = Number.isFinite(n) ? n : 3;
  }
  if (f['confirm_seconds']) {
    const g = (c.confirmation_window || {}).global || {};
    const s = parseFloat(g.seconds);
    f['confirm_seconds'].value = Number.isFinite(s) ? Math.round(s) : 5;
  }
  // detection_trigger lives as a hidden input on the Erkennung tab during
  // this transition; the follow-up commit moves it to a visible select on
  // the Allgemein tab. Either way we set the value so save preserves it.
  if (f['detection_trigger'])
    f['detection_trigger'].value = c.detection_trigger || 'motion_and_objects';
}
