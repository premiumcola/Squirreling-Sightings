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
// THE LABEL LIVES IN THE FREE PART OF THE TRACK. It sat centred over the
// middle at first, where the handle kept colliding with it. Now each end
// carries a copy of the readout that fades in as the handle moves AWAY
// from it, so the span is always in the space the handle just vacated.
//
// EVERYTHING VISIBLE IS DRAWN, NOT NATIVE. The bar, its fill and its
// handle are ordinary elements positioned off one custom property this
// module writes (`--ws-range-pos`); the range input itself is an
// invisible overlay that only contributes the drag, the arrow keys and
// the accessibility role. Two earlier passes styled the input's own
// ::-webkit-/::-moz- pseudo-elements and came back from the operator's
// phone as a hairline with the system handle on it — see the long note
// in 23-weather-3.css for why that path is gone for good.
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
 * PURE: the window as the operator reads it, in the unit that fits.
 *
 * Hours up to two days, then days, then months — „In h day months!". A
 * month is 30.44 days (365.25/12), so „12 Mon." means a year rather
 * than eleven-and-a-bit. Rounded, never truncated: this is a label on a
 * fluid control, not an exact quantity to compute with.
 */
export function formatRangeHours(hours) {
  if (!Number.isFinite(hours) || hours <= 0) return '—';
  if (hours < 48) return `${Math.round(hours)} h`;
  const days = hours / 24;
  if (days < 60) return `${Math.round(days)} d`;
  return `${Math.round(days / 30.4375)} Mon.`;
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

/** Where the crossfade between the two end markers happens, as a
 *  fraction of the track. Outside this band exactly one of them is up;
 *  inside, they trade places. Narrow on purpose — two half-visible
 *  markers is the muddy state worth passing through quickly. */
const _CROSSFADE = [0.34, 0.66];

/**
 * PURE: how strongly each end's readout reads for a handle at `tick`.
 *
 * `near` is the copy on the right — full while the handle sits left,
 * gone once it has travelled past the band. `far` is the copy on the
 * left and does the opposite. Each is only ever shown in the part of the
 * track the handle is not occupying, which is what keeps the span
 * legible without ever putting text under the handle.
 */
export function zoneOpacity(tick) {
  const t = Math.max(0, Math.min(1, (Number(tick) || 0) / TICKS));
  const [lo, hi] = _CROSSFADE;
  const far = Math.max(0, Math.min(1, (t - lo) / (hi - lo)));
  return { near: 1 - far, far };
}

/** Paint the markers and the fill for the handle's current position.
 *
 * Optional chaining throughout, deliberately: the node tests stub
 * `document` with plain objects that carry no `style`, the same
 * convention every other module here is tested under. Painting is
 * decoration — it must never be the reason a render throws. */
function _paintRange(tick, bounds) {
  const text = formatRangeHours(hoursAtTick(tick, bounds));
  const o = zoneOpacity(tick);
  for (const [id, opacity] of [
    ['weatherRangeNear', o.near],
    ['weatherRangeFar', o.far],
  ]) {
    const zone = byId(id);
    if (!zone) continue;
    if (zone.style) zone.style.opacity = String(opacity);
    const label = zone.querySelector?.('.ws-range-zone-text');
    if (label) label.textContent = text;
  }
  // THE one number the drawn slider reads. The fill's width and the
  // handle's offset are both `calc()`s off this 0…1 position, so a drag
  // writes a single property and CSS moves everything that has to move —
  // see 23-weather-3.css for why none of it is browser chrome any more.
  byId('weatherStatsRange')?.style?.setProperty?.('--ws-range-pos', String(tick / TICKS));
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
  // a live one that snaps back is not. The class is what the drawn parts
  // read — `:disabled` only reaches the invisible input.
  input.disabled = !(bounds.max > bounds.min);
  byId('weatherStatsRange')?.classList?.toggle?.('is-locked', input.disabled);
  input.setAttribute('aria-valuetext', formatRangeHours(hours));
  _paintRange(Number(input.value), bounds);
  return hours;
}

/** The handle's own geometry, mirroring 23-weather-3.css exactly:
 *  a 40 px handle inset 4 px, so its CENTRE can only ever reach from
 *  24 px to `width - 24 px`. Positions outside that band are the ends of
 *  the scale, not values beyond it. */
const _THUMB = 40;
const _INSET = 4;
const _PAD = _INSET + _THUMB / 2;

/** PURE: where a pointer at `clientX` puts the handle, in ticks. */
export function tickAtClientX(clientX, rect) {
  const width = rect?.width || 0;
  const usable = width - 2 * _PAD;
  const x = Number(clientX);
  // A pointer event without usable coordinates is not a position of
  // zero — but it must not become NaN either, which would sail straight
  // through Math.max/min and end up written into the input's value.
  if (!(usable > 0) || !Number.isFinite(x)) return 0;
  const t = (x - (rect.left || 0) - _PAD) / usable;
  return Math.round(Math.max(0, Math.min(1, t)) * TICKS);
}

/**
 * THE TRACK IS THE CONTROL, not the handle.
 *
 * „man kriegt ihn beim ersten Mal schwer zu packen, so als wär er in
 * einem ganz kleinen Bereich". That was real, and it was mine: a range
 * input starts a drag only when the gesture BEGINS on its native thumb,
 * and that thumb is invisible here — worse, with the input's own track
 * pseudo-element unstyled, the thumb is only as tall as a default track,
 * so the actual grab zone was a thin band across the middle of a 48 px
 * bar. Everything outside it did nothing at all.
 *
 * So the gesture is ours now: a press ANYWHERE on the pill puts the
 * handle under the finger and keeps it there until release. The input
 * stays for the keyboard and the accessibility tree — the same division
 * of labour the drawn slider already uses for its looks. `setPointer-
 * Capture` is what keeps a fast drag that leaves the bar vertically from
 * being dropped mid-gesture.
 */
function _wireTrackDrag(track, input, onPick, getExtent) {
  let holding = false;
  const at = (e) => {
    const rect = track.getBoundingClientRect?.();
    if (!rect) return;
    input.value = String(tickAtClientX(e.clientX, rect));
    _paintRange(Number(input.value), _boundsOf(input, getExtent()));
  };
  track.addEventListener('pointerdown', (e) => {
    if (input.disabled) return;
    holding = true;
    input.dataset.dragging = '1';
    track.setPointerCapture?.(e.pointerId);
    at(e);
    // The pill declares `touch-action: none`, so this only suppresses the
    // text-selection drag a press-and-move would otherwise start.
    e.preventDefault?.();
  });
  track.addEventListener('pointermove', (e) => holding && at(e));
  for (const done of ['pointerup', 'pointercancel']) {
    track.addEventListener(done, (e) => {
      if (!holding) return;
      holding = false;
      input.dataset.dragging = '0';
      at(e);
      onPick(hoursAtTick(Number(input.value), _boundsOf(input, getExtent())));
    });
  }
}

/**
 * Wire the slider once. `onPick(hours)` fires when the operator settles.
 *
 * Two paths reach it. The pointer one is `_wireTrackDrag` above and owns
 * the whole pill. The keyboard one is the input's own `input`/`change`
 * pair: `input` fires per arrow key and only repaints, `change` is the
 * commit and the only one that costs a history fetch.
 */
export function bindRangeSlider(onPick, getExtent = () => null) {
  const input = byId('weatherRangeSlider');
  if (!input || input.dataset.wired) return;
  input.addEventListener('input', () =>
    _paintRange(Number(input.value), _boundsOf(input, getExtent())),
  );
  input.addEventListener('change', () => {
    input.dataset.dragging = '0';
    onPick(hoursAtTick(Number(input.value), _boundsOf(input, getExtent())));
  });
  // See _isBeingHeld: a 60 s auto-refresh must not move a handle that is
  // currently under a thumb — for the keyboard that is focus, for the
  // pointer it is the flag _wireTrackDrag sets.
  const track = input.closest?.('.ws-range-track') || input.parentElement;
  if (track) _wireTrackDrag(track, input, onPick, getExtent);
  input.dataset.wired = '1';
}
