// ─── mediathek/_view-toggle.js ──────────────────────────────────────────────
// Single source of truth for which of the merged Mediathek section's
// three mutually-exclusive states is visible: the camera-tile overview
// (#mediaOverview), the per-camera drilldown (#mediaDrilldown), or the
// merged /api/library results grid (#libraryBlock). Exactly one is ever
// shown; the other two are `display:none`.
//
// A true leaf module (only core/dom.js) on purpose — mediathek/_drilldown.js
// already owns states 1+2 but drags in bulk-delete.js/media-loader.js/
// filters.js/_paging.js (which in turn pulls in lightbox.js), and
// library/page.js (state 3) needs to flip this toggle without pulling
// that whole graph in — the same "leaf module, reusable without the
// weight" reasoning library/_motion-open.js's own header documents for
// the identical problem.
import { byId } from '../core/dom.js';

const _VIEW_IDS = ['mediaOverview', 'mediaDrilldown', 'libraryBlock'];

/** Show exactly one of the three states by id, hide the other two. */
export function showMediathekView(which) {
  _VIEW_IDS.forEach((id) => {
    const el = byId(id);
    if (el) el.style.display = id === which ? '' : 'none';
  });
}
