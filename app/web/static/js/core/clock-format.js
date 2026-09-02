// ─── core/clock-format.js ──────────────────────────────────────────────────
// Playhead clock formatters. Pure arithmetic on seconds — no DOM, no
// element, nothing to stub — so any module can import them and still be
// unit-testable under a bare `node --test`.
//
// That importability is the reason they live here rather than beside
// the transport that first needed them: mediaview/player/_transport.js
// pulls in _native.js and _pip.js, both of which publish a `window.x`
// bridge at module scope, so importing it outside a browser needs the
// DOM stub in app/tests/_node_js.py. A second player that wanted a
// `m:ss` readout would then have had the choice of dragging that whole
// graph into its tests or writing `m:ss` a fourth time. It is already
// written three times in this codebase (mediathek/_cards.js::_fmtDur
// and weather/_feed.js::_wsFmtDur are the other two, both private,
// both ROUNDING); this file is the one every clock reads from.

/**
 * Seconds → `m:ss`, FLOORED — a running clock, not a rounded duration.
 *
 * The distinction is deliberate and load-bearing: mediathek's card
 * badge rounds, so a 5.6 s clip reads "0:06", which is right for a
 * duration label and wrong for a playhead, where it would make the
 * readout tick over a second early. Minutes keep counting past 60
 * (there is no h:mm:ss branch) because no clip in this archive is an
 * hour long.
 *
 * Non-finite and negative input reads `0:00` rather than `NaN:NaN`.
 *
 * @param {number} seconds
 * @returns {string}
 */
export function clockLabel(seconds) {
  const s = Number.isFinite(seconds) && seconds > 0 ? Math.floor(seconds) : 0;
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/**
 * Time left, rendered the way the native player does — U+2212 MINUS
 * SIGN prefix, not an ASCII hyphen. Pinned by
 * app/tests/test_recorded_player_chrome.py.
 *
 * @param {number} current   playhead position in seconds
 * @param {number} duration  clip length in seconds
 * @returns {string}
 */
export function remainingLabel(current, duration) {
  const dur = Number.isFinite(duration) && duration > 0 ? duration : 0;
  const cur = Number.isFinite(current) && current > 0 ? current : 0;
  return `−${clockLabel(Math.max(0, dur - cur))}`;
}
