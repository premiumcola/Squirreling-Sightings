// ─── mediathek/bbox-overlay/fetcher.js ─────────────────────────────────────
// Sidecar fetch + cache management. Tracks.json lives next to each
// motion-clip mp4 (same /media/ route serves both). lbLoadTracksForItem
// is the public entry called from openLightbox after the video src is
// set; the RAF loop kicks off via the play/loadedmetadata listeners.
import { lbState } from '../state.js';
import { trackColor } from '../../core/track-color.js';
import {
  _reindexFinalFailed,
  _reindexInflight,
  _tracksCache,
  _tracksInflight,
} from './_state.js';
import { _logDiag } from './debug.js';
import {
  _hideReindexBanner,
  _showReindexBannerError,
  _showReindexBannerPending,
} from './reindex.js';
import { _lbDrawDetections } from './renderer.js';
import { _renderConfidenceMeter } from './confidence-meter.js';
import { lbRenderTrackTimeline } from './timeline-panel.js';

export function _tracksUrlFor(item){
  const rel = item?.video_relpath;
  if (!rel) return null;
  // The mp4 lives at <storage>/motion_detection/<cam>/<date>/<id>.mp4
  // and the sidecar sits next to it as <id>.tracks.json. Same /media/
  // route serves both.
  if (rel.endsWith('.mp4')) return `/media/${rel.slice(0, -4)}.tracks.json`;
  return null;
}

export async function _fetchTracks(item){
  const eid = item?.event_id;
  const url = _tracksUrlFor(item);
  if (!eid || !url) return null;
  if (_tracksCache.has(eid)) return _tracksCache.get(eid);
  if (_tracksInflight.has(eid)) return _tracksInflight.get(eid);
  const p = (async () => {
    try {
      const bustUrl = `${url}?_t=${Date.now()}`;
      const r = await fetch(bustUrl, { cache: 'no-store' });
      if (!r.ok){
        _tracksCache.set(eid, null);
        _logDiag(
          `event=${eid} fetch status=${r.status} url=${url} → no tracks`,
          r.status === 404 ? 'info' : 'warn');
        return null;
      }
      const data = await r.json();
      // Sort each track's samples by frame index AND stamp a stable
      // per-clip 1-based number (`_num`) onto every track + ensure
      // tr.color is set (legacy sidecars without it derive a stable
      // hex via the shared core/track-color.js palette). The bbox
      // renderer, characteristic card AND timeline panel all read
      // tr.color directly — stamping once here keeps them in lock-
      // step without each consumer running its own fallback chain.
      let _num = 0;
      for (const tr of (data.tracks || [])){
        (tr.samples || []).sort((a, b) => a.f - b.f);
        _num += 1;
        tr._num = _num;
        tr.color = trackColor(tr);
      }
      _tracksCache.set(eid, data);
      const fa = Array.isArray(data.filter_applied)
        ? data.filter_applied.join(',') : 'none';
      _logDiag(
        `event=${eid} fetch status=200 schema=${data.schema ?? '?'} `
        + `tracks=${(data.tracks || []).length} filter=${fa}`,
        'info');
      return data;
    } catch (e) {
      _tracksCache.set(eid, null);
      _logDiag(`event=${eid} fetch error: ${e?.message || e}`, 'warn');
      return null;
    } finally {
      _tracksInflight.delete(eid);
    }
  })();
  _tracksInflight.set(eid, p);
  return p;
}

// Reset the cached payload for an event so the next render fetches a
// fresh tracks.json (fired after a successful re-index POST).
export function lbInvalidateTracks(eventId){
  if (eventId) _tracksCache.delete(eventId);
}

// Public entry: load tracks for the just-opened item and prime the
// timeline. Called from openLightbox after the video src is set; the
// RAF loop kicks off via the play/loadedmetadata listeners.
//
// I1 · LOAD-ONLY behaviour. tracks.json is generated EXACTLY ONCE at
// recording finalize (see camera_runtime/_recording.py · the
// TrackingJob enqueue) and persisted as the <video>.tracks.json
// sidecar. Every subsequent open just FETCHES and renders that
// sidecar — no automatic re-index, no worker activity. The user can
// still regenerate explicitly via the "Neu indexieren" pill button
// (reindex-button.js → triggerManualReindex) or the banner retry.
// Old clips with no sidecar show a calm placeholder ("noch nicht
// indexiert — über »Neu indexieren« erzeugen") that the user can act
// on; the indexer never starts on its own.
export async function lbLoadTracksForItem(item){
  if (!item) return;
  const tracks = await _fetchTracks(item);
  item._tracks = tracks;
  if (lbState.item !== item) return;

  const haveAnyTracks = !!(tracks
    && Array.isArray(tracks.tracks) && tracks.tracks.length > 0);
  const triggerDetCount = (item.detections || [])
    .filter(d => d && d.bbox && typeof d.bbox.x1 === 'number').length;
  // Render whatever the sidecar produced — including the empty/
  // missing case, where lbRenderTrackTimeline draws the
  // un-indexed placeholder.
  lbRenderTrackTimeline(item);
  _lbDrawDetections();
  if (haveAnyTracks) _renderConfidenceMeter();

  // Banner state — surface ongoing manual reindexes / prior
  // failures but never kick a new one.
  if (_reindexFinalFailed.has(item.event_id)){
    _showReindexBannerError(item);
  } else if (_reindexInflight.has(item.event_id)){
    _showReindexBannerPending(item);
  } else {
    _hideReindexBanner();
  }

  _logDiag(
    `event=${item.event_id} render path=${haveAnyTracks ? 'tracks' : 'placeholder'} `
    + `(${haveAnyTracks ? tracks.tracks.length : 0} tracks, `
    + `${triggerDetCount} trigger dets) — load-only`,
    'info');
}
