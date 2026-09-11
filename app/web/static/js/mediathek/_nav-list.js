// ─── mediathek/_nav-list.js ────────────────────────────────────────────────
// WHAT THE PLAYER PAGES THROUGH — said out loud, by whoever painted the
// grid, instead of guessed from a global.
//
// THE BUG THIS EXISTS FOR. The player stepped `state._allMedia`, which
// is the per-camera drilldown's own pool: every clip of the selected
// camera, narrowed by state.mediaLabels / mediaSpecies, newest first.
// Inside that drilldown it is exactly right. But TWO other grids open
// the same player:
//
//   #libraryGrid   the merged feed, whose items live in library/page.js's
//                  own module-private `_items`, filtered and paged by a
//                  completely different model (cursor + libraryQueryParams)
//                  and never written into state._allMedia at all.
//   the Sichtungen clip accordion, which swaps only `state.media`.
//
// Open a clip from either and the player looked it up in the DRILLDOWN's
// pool — stale from whatever camera was opened last, or empty if none
// ever was — did not find it, and silently fell back to index 0. From
// there „next" walked a list that had nothing to do with what was on
// screen: „Der media player blättert nicht so die videos hin und her wie
// sie dahinter durch die filter in der mediathek ausgewählt sind."
//
// The fix is not a cleverer lookup. It is that the question „what comes
// after this one" belongs to the grid that is showing, and only that
// grid can answer it. Each one now says so when it paints.
//
// LAST PAINT WINS, deliberately — the same convention the existing
// `window._openMediaItem` bridge already follows (mediathek/_paging.js
// and library/_bind.js overwrite each other on that global too). Exactly
// one of the four Mediathek states is ever visible, so the grid that
// painted last is the grid the operator is looking at.

let _items = [];

/** Declare the ordered list the player should page through. Called by
 *  every grid that can open the player, right where it paints. */
export function setMediaNavList(items) {
  _items = Array.isArray(items) ? items : [];
}

/** The current list. Never null; `[]` before any grid has painted. */
export function mediaNavList() {
  return _items;
}

/** PURE: where `eventId` sits in `list`, or -1.
 *
 * -1 is a real answer and the caller must honour it: an item that is not
 * in the list has NO neighbours. The old code turned "not found" into
 * index 0, which is how a clip opened from one grid started paging
 * through another one. */
export function navIndexOf(list, eventId) {
  if (!eventId) return -1;
  return (list || []).findIndex((x) => x && x.event_id === eventId);
}
