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

/**
 * ONE class-filter row on screen at a time — „Filter sind doppelt drin!".
 *
 * #libraryFilterBar sits above all four states and filters the merged
 * feed (#libraryBlock). The drilldown brings its own bar (#mediaFilterBar,
 * mediathek/filters.js) for the grid it actually shows. With the drilldown
 * open both were visible: two rows of the same taxonomy, one of them
 * filtering a grid that was not on screen, each with its own count for
 * „Vogel". The bar whose grid is hidden goes with it.
 *
 * library/page.js keeps its own closeMediaDrilldown bridge for the
 * programmatic path (a quick tile, a reset) — this only decides what the
 * operator can see and tap.
 */
function _syncFilterBar(which) {
  const bar = byId('libraryFilterBar');
  if (bar) bar.style.display = which === 'mediaDrilldown' ? 'none' : '';
}

/** The way out of each state that has one. `mediaOverview` is the root
 *  and has none — from there the arrow is simply not there. */
const _BACK_ACTION = {
  mediaDrilldown: 'closeMediaDrilldown',
  mediaSpeciesGrid: 'closeMediaSpeciesGrid',
  libraryBlock: 'resetLibraryView',
};

/**
 * ONE back arrow, in the section head beside the title.
 *
 * Each of the three states used to carry its own full-width „← Alle
 * Kameras" / „← Übersicht" bar, which is a whole row of a phone screen
 * spent on a word the arrow already says — „vielleicht könntest Du den
 * so gestalten, dass der 'n Zurückpfeil ist ohne Übersicht […] nicht als
 * einzelne Zeile, sondern oben neben dem Mediathek-Titel". The three
 * actions differ, so the button takes the one belonging to whatever is
 * showing; the toggle is the only place that already knows.
 */
function _syncBackButton(which) {
  const btn = byId('mediaBackBtn');
  if (!btn) return;
  const action = _BACK_ACTION[which];
  btn.hidden = !action;
  if (action) btn.dataset.action = action;
}

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
  _syncFilterBar(which);
  _syncBackButton(which);
  _shown = which;
  if (!changed) return;
  const reduce = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
  // THE SECTION, NOT THE STATE. Scrolling the state container to the top
  // of the viewport put its own first card there — and pushed the
  // section title, the back arrow and the filter row off the top edge:
  // „es zoomt mir komplett zu weit runter. Ich seh die Mediathek oben den
  // Titel und auch die Filter nicht mehr." What the operator needs in
  // view after a filter is the filter they just used, with its result
  // under it. #media is that frame; the state is only its lower half.
  const anchor = byId('media') || byId(which);
  anchor?.scrollIntoView?.({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
}
