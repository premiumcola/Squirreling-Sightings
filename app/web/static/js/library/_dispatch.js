// ─── library/_dispatch.js ────────────────────────────────────────────────
// Stage 4 of the Mediathek + Wetter-Ereignisse merge: the one function
// that turns any `/api/library` item into card HTML, by adapting it and
// handing it to whichever existing builder already owns that kind's
// markup. No new card HTML is written here for a kind that already has
// a builder — see the adapter modules for exactly which fields each one
// renames/reshapes and why.
//
// Split out of index.js (rather than living there directly) so
// `_grid.js` can import the dispatcher without an index.js ⇄ _grid.js
// import cycle — index.js only re-exports both.
import { esc } from '../core/dom.js';
import { mediaCardHTML } from '../mediathek/_cards.js';
import {
  sightingCardHTML,
  recapCardHTML,
  manualEventCardHTML,
  episodeCardHTML,
} from '../weather/_feed.js';
import { adaptMotionItem } from './_motion-adapter.js';
import {
  adaptSightingItem,
  adaptRecapItem,
  adaptManualItem,
  adaptEpisodeItem,
} from './_weather-adapters.js';
import { timelapseCardHTML } from './_timelapse-card.js';

/**
 * A card for a kind this dispatcher doesn't (yet) recognise — a future
 * server-side kind, or a malformed item. Renders SOMETHING rather than
 * throwing, so one bad item cannot blank the whole grid; matches the
 * fallback contract `manualCategoryMeta`/`characterMeta` already give an
 * unrecognised sub-value elsewhere in this codebase (grey, no icon, key
 * as label — never a crash).
 */
function _fallbackCardHTML(item) {
  const kind = (item && item.kind) || 'unbekannt';
  const label = (item && (item.cam_name || item.cam_id)) || '';
  return `<article class="media-card lib-card--unknown" data-lib-kind="${esc(kind)}">
      <div class="mmc-img-wrap" style="display:flex;align-items:center;justify-content:center;color:#94a3b8;font-size:11px;text-align:center;padding:8px">
        ${esc(kind)}${label ? `<br>${esc(label)}` : ''}
      </div>
    </article>`;
}

/**
 * One `/api/library` item → card HTML, dispatched on `item.kind`.
 *
 * `ctx` carries positional info a couple of the underlying builders need:
 *   - `idx` — the item's position within the CURRENT page. Fed to
 *     `sightingCardHTML`/`recapCardHTML`, which use it for their
 *     `data-idx`/`data-recap-idx` (real lightbox prev/next wiring is a
 *     Stage 6 concern, once this grid actually replaces the old
 *     sections and can track a true cross-page absolute index).
 *   - `pageItems` — unused by any adapter today; carried so a future
 *     card (or the Stage 6 lightbox wiring) can look at neighbouring
 *     items without the dispatcher growing a second signature.
 */
export function libraryCardHTML(item, ctx = {}) {
  if (!item || typeof item.kind !== 'string') return _fallbackCardHTML(item);
  const idx = Number.isInteger(ctx.idx) ? ctx.idx : 0;
  switch (item.kind) {
    case 'motion':
      return mediaCardHTML(adaptMotionItem(item));
    case 'sighting':
      // idx: this item's position within the current PAGE, not a true
      // cross-page absolute index — see the ctx doc above.
      // isActive=false: `sightingCardHTML`'s real semantic for this
      // flag is "is the sighting's camera still in the active config"
      // (weather/_feed.js's own comment), which needs `state.cameras` —
      // this standalone package isn't wired into any page's live state
      // yet (that's explicitly a later stage), so there is nothing
      // honest to answer "true" with. `false` is the same conservative
      // default the rest of this stage takes for anything it cannot
      // verify yet: a dimmed thumb, never a wrong claim of liveness.
      return sightingCardHTML(adaptSightingItem(item), idx, false);
    case 'recap':
      return recapCardHTML(adaptRecapItem(item), idx);
    case 'manual':
      return manualEventCardHTML(adaptManualItem(item));
    case 'episode':
      return episodeCardHTML(adaptEpisodeItem(item));
    case 'timelapse':
      return timelapseCardHTML(item);
    default:
      return _fallbackCardHTML(item);
  }
}
