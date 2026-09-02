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
// PROVENANCE HAS TWO SOURCES and they are not the same shape. The media
// list route hands the whole event JSON through, so an item opened from
// the grid usually carries `provenance` already. A deep link resolves
// through /api/event/<id>, which is a NARROW projection — it carries
// provenance but not detections. Preferring the item and falling back
// to the endpoint covers both without a second request in the common
// case.

import { _fetchTracks } from '../../mediathek/bbox-overlay/fetcher.js';
// The row mapping is pure and lives with the other pure mappings, so
// it is provable under a bare `node --test` — this file cannot be,
// because the fetcher's module graph publishes a window bridge.
import { objectRowsFor, objectsNote } from './_map.js';
export { objectRowsFor, objectsNote } from './_map.js';

/**
 * Fetch the provenance block for an event.
 *
 * @returns {Promise<object|null>} null on any failure — a panel that
 *   cannot say how a clip was made still has to render the clip.
 */
export async function fetchProvenance(eventId) {
  if (!eventId) return null;
  try {
    const r = await fetch(`/api/event/${encodeURIComponent(eventId)}`, { cache: 'no-store' });
    if (!r.ok) return null;
    const data = await r.json();
    return data && data.provenance ? data.provenance : null;
  } catch {
    return null;
  }
}

/**
 * Load everything the recorded panel needs for one item.
 *
 * @param {object} item  the mediathek event item
 * @returns {Promise<{item, tracks, provenance, rows, note}>}
 */
export async function loadRecorded(item) {
  const tracks = await _fetchTracks(item);
  const provenance = item?.provenance || (await fetchProvenance(item?.event_id));
  const rows = objectRowsFor(item, tracks);
  return { item, tracks, provenance, rows, note: objectsNote(rows, item) };
}
