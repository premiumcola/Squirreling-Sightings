// ─── weather/_range-slider.js ──────────────────────────────────────────────
// The Wetterdaten time chooser: ONE slider, „nah" on the left, „fern" on
// the right, told what the archive can actually fill.
//
// It replaces the five fixed steps (1 h / 6 h / 24 h / 7 d / 30 d) that
// used to sit here as a pill row — „mach unten am besten nicht diese
// festen Zeiträume, sondern son Slider von links nach rechts […] von
// nahe […] zu maximalen Zeitraum". The ladder BEHIND it is unchanged:
// the same hour values, the same `/api/weather/history?hours=` fetch,
// the same extent handling. This is a new input surface over the
// existing range concept, not a new data model — so a slider notch and
// the old pill mean bit-for-bit the same thing downstream.
//
// The offered steps still come from the markup (`data-steps` on the
// input) rather than a constant in here, exactly the way the pill bar
// used to read them off its own buttons.
//
// The extent comes from the payload (`_history.py::history` reports the
// buffer's own oldest/newest/count) rather than being inferred from the
// samples that came back: asking for 30 d and receiving 3 h is
// indistinguishable, client-side, from a service that only kept 3 h.

import { byId } from '../core/dom.js';

/** Hours the archive spans, or null when it cannot say. */
export function archiveSpanHours(extent) {
  if (!extent || (extent.count ?? 0) < 2) return null;
  const first = Date.parse(extent.oldest ?? '');
  const last = Date.parse(extent.newest ?? '');
  if (!Number.isFinite(first) || !Number.isFinite(last) || last <= first) return null;
  return (last - first) / 3_600_000;
}

/** `"1,6,24"` → `[1, 6, 24]` — deduped, sorted, junk dropped. */
export function parseSteps(csv) {
  const raw = String(csv ?? '')
    .split(',')
    .map((s) => parseInt(s, 10))
    .filter((h) => Number.isFinite(h) && h > 0);
  return [...new Set(raw)].sort((a, b) => a - b);
}

/**
 * The slider's domain, and where the handle sits on it.
 *
 * A step is DROPPED when a smaller step already covers the whole
 * archive — it would show nothing the smaller one does not, and „30 d"
 * over three hours of data draws a month-wide axis of flat weather that
 * reads as a broken service rather than a young archive. One step of
 * headroom is deliberate: the first step at or above the archive's span
 * stays, because that is the „show me everything I have" position.
 *
 * Dropping rather than disabling is what the slider makes possible in
 * the first place: an unreachable notch in the middle of a track has no
 * affordance at all, while a track that simply ends short of „fern" is
 * self-explanatory.
 *
 * The handle only moves when it has to — with plenty of history the
 * panel keeps its 24 h; it falls back to the widest step that still has
 * data only when the current one has gone off the end.
 */
export function rangeSliderPlan(spanHours, offered, current) {
  const steps = Array.isArray(offered) ? parseSteps(offered.join(',')) : parseSteps(offered);
  if (!steps.length) return { steps: [], index: 0, hours: current };
  // `undefined` when the span is unknown, or longer than every step —
  // in both cases nothing is dropped.
  const covering = Number.isFinite(spanHours) ? steps.find((h) => h >= spanHours) : undefined;
  const usable = covering === undefined ? steps : steps.filter((h) => h <= covering);
  const at = usable.indexOf(current);
  const index = at >= 0 ? at : usable.length - 1;
  return { steps: usable, index, hours: usable[index] };
}

/** The step a handle position names, or null when it names none. */
export function hoursAtIndex(steps, index) {
  if (!Array.isArray(steps) || !steps.length) return null;
  const n = Number(index);
  if (!Number.isFinite(n)) return null;
  return steps[Math.max(0, Math.min(steps.length - 1, Math.trunc(n)))];
}

/**
 * The chosen range as the operator reads it — „24 h", „7 d". Days only
 * from two days up: „1 d" would be a second name for the step everyone
 * in this app (and the old pill bar) already calls 24 h.
 */
export function formatRangeHours(hours) {
  if (!Number.isFinite(hours) || hours <= 0) return '—';
  if (hours < 48) return `${hours} h`;
  const days = hours / 24;
  return Number.isInteger(days) ? `${days} d` : `${hours} h`;
}

// A drag-zoom on the chart matches no step on the ladder, so the
// readout must not keep claiming one — same reason every pill used to go
// dark. The ✕ chip next to the slider is the way back.
const CUSTOM_RANGE = 'eigener Zeitraum';

/** What the readout next to the handle says right now. */
export function rangeReadoutText(hours, zoomed) {
  return zoomed ? CUSTOM_RANGE : formatRangeHours(hours);
}

// The chart re-fetches itself every 60 s while the section is on
// screen, and each of those renders lands here. Writing `value` back
// onto a handle the operator is still holding would yank it out from
// under their thumb, so a render that arrives mid-interaction updates
// everything EXCEPT the handle position — the next `change` writes the
// real choice anyway. Focus covers the keyboard case (arrow keys hold
// focus for as long as the operator wants), `data-dragging` the pointer
// one, since not every browser focuses a range input on pointerdown.
function _isBeingHeld(input) {
  return input.dataset.dragging === '1' || globalThis.document?.activeElement === input;
}

/**
 * Apply the plan to the live slider. Returns the range the panel should
 * be on, so the caller can switch to it if the current one went off the
 * end. Idempotent — safe to run on every render.
 *
 * The usable subset is parked back on the element (`data-usable`) so the
 * change handler can map a handle index onto an hours value without this
 * module holding mutable state of its own.
 */
export function applyRangeSlider(extent, currentHours, zoomed = false) {
  const input = byId('weatherRangeSlider');
  if (!input) return null;
  const plan = rangeSliderPlan(
    archiveSpanHours(extent),
    parseSteps(input.dataset.steps),
    currentHours,
  );
  if (!plan.steps.length) return null;
  input.dataset.usable = plan.steps.join(',');
  input.min = '0';
  input.max = String(plan.steps.length - 1);
  input.step = '1';
  if (!_isBeingHeld(input)) input.value = String(plan.index);
  // A one-step archive has nothing to choose between; a dead handle is
  // honest, a live one that snaps back is not.
  input.disabled = plan.steps.length < 2;
  const text = rangeReadoutText(plan.hours, zoomed);
  input.setAttribute('aria-valuetext', text);
  const out = byId('weatherRangeValue');
  if (out && !_isBeingHeld(input)) out.textContent = text;
  return plan.hours;
}

/**
 * Wire the slider once. `onPick(hours)` fires when the operator settles
 * on a step.
 *
 * Two listeners on purpose: `input` fires per pixel while dragging and
 * only moves the readout, so the handle is never a blind control;
 * `change` is the commit (pointer-up on desktop, touch-end on iOS) and
 * is the only one that costs a history fetch.
 */
export function bindRangeSlider(onPick) {
  const input = byId('weatherRangeSlider');
  if (!input || input.dataset.wired) return;
  const hoursNow = () =>
    hoursAtIndex(parseSteps(input.dataset.usable || input.dataset.steps), input.value);
  input.addEventListener('input', () => {
    const h = hoursNow();
    const out = byId('weatherRangeValue');
    if (out && h != null) out.textContent = formatRangeHours(h);
  });
  input.addEventListener('change', () => {
    input.dataset.dragging = '0';
    const h = hoursNow();
    if (h != null) onPick(h);
  });
  // See _isBeingHeld: a 60 s auto-refresh must not move a handle that is
  // currently under a thumb. `pointercancel` matters on iOS, where a
  // drag that turns into a page scroll ends that way and never fires
  // `change` — without it the flag would latch on forever.
  input.addEventListener('pointerdown', () => (input.dataset.dragging = '1'));
  for (const done of ['pointerup', 'pointercancel']) {
    input.addEventListener(done, () => (input.dataset.dragging = '0'));
  }
  input.dataset.wired = '1';
}
