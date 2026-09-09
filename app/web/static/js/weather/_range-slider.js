// ─── weather/_range-slider.js ──────────────────────────────────────────────
// The Wetterdaten time zoom: ONE continuous slider, near on the left,
// far on the right, told what the archive can actually fill.
//
// FLUID, NOT NOTCHED. It began as five fixed steps (1 h / 6 h / 24 h /
// 7 d / 30 d) in a pill row, then as a slider that still snapped to
// those five — „Flüssiger slider nicht mit festen marken!". Any window
// between one hour and the archive's own span is reachable now; the
// ladder is gone, and `hours=` has always accepted an arbitrary number,
// so nothing downstream had to learn anything.
//
// LOGARITHMIC, because the useful range spans three orders of magnitude
// (1 h … 720 h). On a linear track the entire first day would live in
// the leftmost 3 % and "yesterday afternoon" would be unhittable with a
// thumb. On a log track every doubling gets equal travel, which is how
// the choice actually feels.
//
// NO TEXT. „ohne text elemente nur symbole" — the two end glyphs carry
// the meaning instead: each fades in as the window moves toward its end
// of the scale, so the control shows where it stands without spelling
// anything out. The chosen span is already written along the chart's own
// x-axis directly underneath, so a readout here would only say it twice.
//
// The extent comes from the payload (`_history.py::history` reports the
// buffer's own oldest/newest/count) rather than being inferred from the
// samples that came back: asking for 30 d and receiving 3 h is
// indistinguishable, client-side, from a service that only kept 3 h.

import { byId } from '../core/dom.js';

/** Track resolution. Fine enough to read as continuous, coarse enough
 *  that a stray pixel does not refetch a different window. */
const TICKS = 1000;

/** Hours the archive spans, or null when it cannot say. */
export function archiveSpanHours(extent) {
  if (!extent || (extent.count ?? 0) < 2) return null;
  const first = Date.parse(extent.oldest ?? '');
  const last = Date.parse(extent.newest ?? '');
  if (!Number.isFinite(first) || !Number.isFinite(last) || last <= first) return null;
  return (last - first) / 3_600_000;
}

/**
 * PURE: the reachable window, in hours.
 *
 * The floor is the shortest window worth drawing; the ceiling is the
 * archive's own span, capped by the configured maximum — offering "30
 * days" over three hours of data draws a month-wide axis of flat weather
 * that reads as a broken service rather than a young archive. A little
 * headroom over the span is deliberate, so the far end always means
 * „everything I have" rather than stopping just short of it.
 */
export function rangeBounds(spanHours, minHours, maxHours) {
  const lo = Math.max(1, Number(minHours) || 1);
  const hard = Math.max(lo, Number(maxHours) || lo);
  const span = Number.isFinite(spanHours) && spanHours > 0 ? spanHours * 1.05 : hard;
  return { min: lo, max: Math.max(lo, Math.min(hard, Math.ceil(span))) };
}

/** PURE: slider position (0…TICKS) → hours, on the log scale. */
export function hoursAtTick(tick, bounds) {
  const { min, max } = bounds;
  if (!(max > min)) return min;
  const t = Math.max(0, Math.min(1, (Number(tick) || 0) / TICKS));
  return Math.max(min, Math.round(Math.exp(Math.log(min) + t * (Math.log(max) - Math.log(min)))));
}

/** PURE: hours → slider position (0…TICKS). The inverse of the above. */
export function tickAtHours(hours, bounds) {
  const { min, max } = bounds;
  if (!(max > min)) return 0;
  const h = Math.max(min, Math.min(max, Number(hours) || min));
  const t = (Math.log(h) - Math.log(min)) / (Math.log(max) - Math.log(min));
  return Math.round(Math.max(0, Math.min(1, t)) * TICKS);
}

/**
 * PURE: how strongly each end glyph reads, for a handle at `tick`.
 *
 * Both stay faintly visible at every position — an end that vanished
 * would take the scale's own shape with it — and the one the window is
 * moving toward comes up to full. Returned as a pair so the caller
 * writes two opacities and nothing else.
 */
export function glyphOpacity(tick) {
  const t = Math.max(0, Math.min(1, (Number(tick) || 0) / TICKS));
  const FLOOR = 0.28;
  const span = 1 - FLOOR;
  return { near: FLOOR + span * (1 - t), far: FLOOR + span * t };
}

// The chart re-fetches itself every 60 s while the section is on screen,
// and each of those renders lands here. Writing `value` back onto a
// handle the operator is still holding would yank it out from under
// their thumb, so a render that arrives mid-interaction updates
// everything EXCEPT the handle position — the next `change` writes the
// real choice anyway. Focus covers the keyboard case, `data-dragging`
// the pointer one, since not every browser focuses a range input on
// pointerdown.
function _isBeingHeld(input) {
  return input.dataset.dragging === '1' || globalThis.document?.activeElement === input;
}

function _boundsOf(input, extent) {
  return rangeBounds(archiveSpanHours(extent), input.dataset.minHours, input.dataset.maxHours);
}

/** Paint the two end glyphs for the handle's current position. */
// Optional chaining throughout, deliberately: the node tests stub
// `document` with plain objects that carry no `style`, the same
// convention every other module here is tested under. Painting is
// decoration — it must never be the reason a render throws.
function _paintGlyphs(tick) {
  const o = glyphOpacity(tick);
  const near = byId('weatherRangeGlyphNear');
  const far = byId('weatherRangeGlyphFar');
  if (near?.style) near.style.opacity = String(o.near);
  if (far?.style) far.style.opacity = String(o.far);
  // The filled part of the track, as a percentage — the "slide to
  // unlock" fill behind the thumb, painted by CSS off this one variable.
  byId('weatherRangeSlider')?.style?.setProperty?.('--ws-range-fill', `${(tick / TICKS) * 100}%`);
}

/**
 * Apply the archive's extent to the live slider. Returns the range the
 * panel should be on, so the caller can switch to it if the current one
 * no longer fits. Idempotent — safe to run on every render.
 */
export function applyRangeSlider(extent, currentHours, _zoomed = false) {
  const input = byId('weatherRangeSlider');
  if (!input) return null;
  const bounds = _boundsOf(input, extent);
  const hours = Math.max(bounds.min, Math.min(bounds.max, Number(currentHours) || bounds.max));
  input.min = '0';
  input.max = String(TICKS);
  input.step = '1';
  const tick = tickAtHours(hours, bounds);
  if (!_isBeingHeld(input)) input.value = String(tick);
  // An archive with nothing to choose between: a dead handle is honest,
  // a live one that snaps back is not.
  input.disabled = !(bounds.max > bounds.min);
  input.setAttribute('aria-valuetext', `${hours} h`);
  _paintGlyphs(Number(input.value));
  return hours;
}

/**
 * Wire the slider once. `onPick(hours)` fires when the operator settles.
 *
 * Two listeners on purpose: `input` fires per pixel while dragging and
 * only repaints the glyphs and the fill, so the handle is never a blind
 * control; `change` is the commit (pointer-up on desktop, touch-end on
 * iOS) and is the only one that costs a history fetch.
 */
export function bindRangeSlider(onPick, getExtent = () => null) {
  const input = byId('weatherRangeSlider');
  if (!input || input.dataset.wired) return;
  input.addEventListener('input', () => _paintGlyphs(Number(input.value)));
  input.addEventListener('change', () => {
    input.dataset.dragging = '0';
    onPick(hoursAtTick(Number(input.value), _boundsOf(input, getExtent())));
  });
  // See _isBeingHeld: a 60 s auto-refresh must not move a handle that is
  // currently under a thumb. `pointercancel` matters on iOS, where a drag
  // that turns into a page scroll ends that way and never fires `change`
  // — without it the flag would latch on for ever.
  input.addEventListener('pointerdown', () => (input.dataset.dragging = '1'));
  for (const done of ['pointerup', 'pointercancel']) {
    input.addEventListener(done, () => (input.dataset.dragging = '0'));
  }
  input.dataset.wired = '1';
}
