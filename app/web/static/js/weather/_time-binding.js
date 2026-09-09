// ─── weather/_time-binding.js ──────────────────────────────────────────────
// Who is allowed to keep the Wetterdaten time chooser's narrowing alive.
//
// The chooser sits at the BOTTOM of the Mediathek section; the class /
// species / camera filters sit at the TOP. A narrowing set down there
// and still in force after the operator has moved on to a filter up here
// is invisible until it bites — „das ist verwirrend […] resette das
// Time Binding auf den Time Chooser unten immer, wenn ich oben eben
// andere Filter verwende. Wenn ich den Time Filter zuletzt verwendet hab
// und danach keine anderen Filter, dann kann er stehen bleiben."
//
// So the rule is last-touch-wins and exactly one bit wide: the narrowing
// survives for as long as the time chooser is the only thing being
// touched, and releases itself the moment ANY other filter dimension is
// used.
//
// This is a leaf module (its only import is `_zoom.js`, itself a leaf)
// precisely so the filter surfaces up the page — mediathek/filters.js,
// mediathek/_drilldown.js, library/page.js — can call into it without
// pulling in the weather chart's own module graph, and so the chart can
// subscribe to the release without any of them importing IT back. Same
// no-cycle reasoning `_zoom.js` already documents for itself.

import { clearZoomRange, isZoomActive } from './_zoom.js';

/** The one source that does NOT release: the time chooser itself — its
 * slider, its ✕ chip, a drag on the chart. Passing this is how a caller
 * says „the operator only touched time". */
export const TIME_SOURCE = 'time';

/**
 * The rule, on its own and free of any state: does a filter interaction
 * from `source` release a currently-`bound` time narrowing?
 *
 * Nothing to release when nothing is bound — releasing an already-open
 * chooser is not an event, and callers use the return value to decide
 * whether a redraw is even needed.
 */
export function releasesTimeBinding(source, bound) {
  return !!bound && source !== TIME_SOURCE;
}

const _subs = new Set();

/** Subscribe to releases. Returns its own unsubscribe. */
export function onTimeBindingRelease(fn) {
  _subs.add(fn);
  return () => _subs.delete(fn);
}

/**
 * Report that a filter of kind `source` was just used, and release the
 * time binding if that kind releases it. Returns whether it did, so a
 * caller that wants to skip a redundant reload can ask.
 *
 * `source` is a free-form tag naming the filter dimension ('label',
 * 'species', 'camera', 'library-chip', …) — only `TIME_SOURCE` is ever
 * compared against, everything else releases.
 */
export function noteFilterUse(source) {
  if (!releasesTimeBinding(source, isZoomActive())) return false;
  clearZoomRange();
  // Copy first: a subscriber is free to unsubscribe itself from inside
  // its own callback.
  for (const fn of [..._subs]) fn(source);
  return true;
}
