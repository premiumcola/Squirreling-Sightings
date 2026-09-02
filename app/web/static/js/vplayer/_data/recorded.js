// ─── vplayer/_data/recorded.js ─────────────────────────────────────────────
// Everything the recorded panel reads, from the two places it lives.
//
// NO SECOND FETCHER. The tracks.json sidecar comes through
// mediathek/bbox-overlay/fetcher.js's _fetchTracks, which already owns
// the per-event cache, the in-flight dedupe (two opens of the same clip
// share one request) and — load-bearing — the stamping of `_num` and
// `color` onto every track. The timeline's lane colours and the box
// strokes both read those, so a second fetcher that skipped the
// stamping would silently paint every track the fallback green.
//
// It deliberately calls _fetchTracks and NOT lbLoadTracksForItem: the
// latter is the same fetch plus a fan-out into the old player's DOM
// (lbRenderTrackTimeline, _lbDrawDetections, _renderConfidenceMeter).
// This player renders its own.
//
// THE ITEM HAS TWO SOURCES and they are not the same shape. The media
// list route hands the whole event JSON through, so an item opened from
// the grid carries everything. /api/event/<id> is a NARROW projection —
// a named key set (routes/media.py::EVENT_LOOKUP_KEYS), and a key it
// does not name is one this player would silently lose. Preferring the
// item and falling back to the endpoint covers both without a second
// request in the common case.
//
// ONE REQUEST, TWO KEYS. The fallback fires on the same trigger it
// always has — an item with no `provenance` — and now keeps
// `whole_clip` off that same response as well. The two travel together:
// an item narrow enough to have lost one lost the other with it, so
// widening the TRIGGER would only spend a request per pre-aggregate clip
// to be told again that it has no aggregate.

import { _fetchTracks } from '../../mediathek/bbox-overlay/fetcher.js';

/**
 * Fetch the narrow cross-camera projection of an event.
 *
 * @returns {Promise<object|null>} null on any failure — a panel that
 *   cannot say how a clip was made still has to render the clip.
 */
export async function fetchEventLookup(eventId) {
  if (!eventId) return null;
  try {
    const r = await fetch(`/api/event/${encodeURIComponent(eventId)}`, { cache: 'no-store' });
    if (!r.ok) return null;
    const data = await r.json();
    return data && typeof data === 'object' ? data : null;
  } catch {
    return null;
  }
}

/**
 * Load everything the recorded panel needs for one item.
 *
 * The object ROWS are deliberately not built here. The panel re-derives
 * them from the item on every paint, because a correction changes the
 * item and the rows have to follow it — a list computed once at load
 * would be a snapshot the panel could never honestly refresh.
 *
 * The item comes back POSSIBLY WIDENED: whatever the lookup recovered is
 * folded into a copy, so every reader downstream — the panel, the rows,
 * the correction sheet — sees one item rather than having to know which
 * route theirs arrived on. The copy is skipped when nothing was
 * recovered, which is the common case.
 *
 * @param {object} item  the mediathek event item
 * @returns {Promise<{item, tracks, provenance}>}
 */
export async function loadRecorded(item) {
  const tracks = await _fetchTracks(item);
  const looked = item?.provenance ? null : await fetchEventLookup(item?.event_id);
  const provenance = item?.provenance || looked?.provenance || null;
  const wholeClip = item?.whole_clip ? null : looked?.whole_clip || null;
  return { item: wholeClip ? { ...item, whole_clip: wholeClip } : item, tracks, provenance };
}
