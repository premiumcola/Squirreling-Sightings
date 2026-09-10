// ─── mediathek/_view-toggle.js ──────────────────────────────────────────────
// Single source of truth for which of the merged Mediathek section's
// four mutually-exclusive states is visible: the camera-tile overview
// (#mediaOverview), the "Vogelarten" species grid (#mediaSpeciesGrid),
// the per-camera drilldown (#mediaDrilldown), or the merged
// /api/library results grid (#libraryBlock). Exactly one is ever
// shown; the other three are `display:none`.
//
// A true leaf module (only core/dom.js) on purpose — mediathek/_drilldown.js
// already owns states 1+3 but drags in bulk-delete.js/media-loader.js/
// filters.js/_paging.js (which in turn pulls in lightbox.js), and
// library/page.js (state 4) AND mediathek/_species-grid.js (state 2)
// need to flip this toggle without pulling that whole graph in — the
// same "leaf module, reusable without the weight" reasoning
// library/_motion-open.js's own header documents for the identical
// problem.
import { byId } from '../core/dom.js';

const _VIEW_IDS = ['mediaOverview', 'mediaSpeciesGrid', 'mediaDrilldown', 'libraryBlock'];

/** The state currently shown, so a switch can be told from a re-render.
 *  `null` until the first call — the initial paint must not scroll. */
let _shown = null;

/**
 * Show exactly one of the four states by id, hide the other three.
 *
 * AND BRING IT INTO VIEW. The four states are stacked inside one long
 * page: the Mediathek section is followed by the weather chart, its
 * legend, three settings folds and the Sichtungen block. Tapping a tile
 * near the bottom of the overview swapped the state in place and left
 * the scroll position where the finger was — so „Vogelarten" answered
 * with a screen full of weather data and the grid sat off-screen above
 * it. „Das ist die screen ansicht wenn ich auf vogelarten klicke?!"
 *
 * Only on a real CHANGE of state: this runs on re-renders too, and
 * scrolling on every one of those would yank the page while the
 * operator is reading it. And never on the first call, which is the
 * initial paint — a page that scrolls itself on load is its own bug.
 */
export function showMediathekView(which) {
  const changed = _shown !== null && which !== _shown;
  _VIEW_IDS.forEach((id) => {
    const el = byId(id);
    if (el) el.style.display = id === which ? '' : 'none';
  });
  _shown = which;
  if (!changed) return;
  const reduce = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
  byId(which)?.scrollIntoView?.({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
}
