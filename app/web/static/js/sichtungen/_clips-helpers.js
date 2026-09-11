// ─── sichtungen/_clips-helpers.js ────────────────────────────────────────
// Pure leaves of the "Eigene Aufnahmen" gallery (_clips-gallery.js).
//
// Separate module on purpose: _clips-gallery.js imports
// mediathek/_cards.js to re-host the real card markup, and that module
// graph reaches mediathek/_processing.js, which assigns to `window` at
// MODULE-LOAD time — so importing the gallery from a node test throws
// `ReferenceError: window is not defined` before a single assertion
// runs. Same wall library/_tests/bind.test.js and
// test_species_dossier_panel_js.py both document. Keeping the logic
// that is worth testing in a leaf with no DOM imports is the established
// answer to it.
import { esc } from '../core/dom.js';

/** Clamp `idx` into `[0, len)`. Returns 0 for an empty list so callers
 *  never have to special-case it before indexing. */
/** How many of a species' clips the gallery loads.
 *
 * A cap, not a page size. The counter under the gallery reads „1 / N"
 * and N used to be whatever had been fetched — eight — beside a medal
 * saying „64×": „wieso zahlenunterschied?". Loading them all makes the
 * counter the real number; a set that actually reaches this cap is
 * marked with a „+" so the display never quietly means something else
 * again.
 */
export const CLIPS_CAP = 200;

export function clampIndex(idx, len) {
  if (!Number.isFinite(idx) || len <= 0) return 0;
  return Math.min(Math.max(Math.trunc(idx), 0), len - 1);
}

/** Video URL for one adapted motion item, or '' when the clip isn't
 *  playable (still-only event, or an encode that failed). Mirrors the
 *  field pair mediathek/_cards.js checks for its own play button, so a
 *  card that SHOWS a play button is exactly one this can play. */
export function clipVideoUrl(item) {
  if (!item) return '';
  if (item.video_url) return item.video_url;
  return item.video_relpath ? `/media/${item.video_relpath}` : '';
}

/** Every empty / dead-end state of the clips column in one place. */
export function clipsMessageHtml(text) {
  return `<div class="sd-clips-empty">${esc(text)}</div>`;
}
