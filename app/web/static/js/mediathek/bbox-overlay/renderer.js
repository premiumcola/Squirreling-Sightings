// ─── mediathek/bbox-overlay/renderer.js ────────────────────────────────────
// Canvas-overlay renderer + per-track interpolation helpers. The MP4 is
// NEVER modified; this paints a separate canvas on top of the media
// element. Track colours come from the deterministic tracks.json
// palette so multiple subjects in one clip get distinguishable strokes.
//
// This file is the ORCHESTRATOR — per-render setup + branch selection.
// The actual painting primitives live in ./_canvas-shapes.js (canvas box
// drawing), the label-visibility gate in ./_classfilter.js, and shared
// style/text resolution in ./_box-style.js — split out so this file and
// its functions stay under CLAUDE.md's size ceilings.
import { byId } from '../../core/dom.js';
import { state } from '../../core/state.js';
import { colors } from '../../core/icons.js';
import { _lbClearDetections } from '../../lightbox.js';
import { lbState } from '../state.js';
import { _TRACK_SPAWN_SCORE } from './_state.js';
import { _isReindexBannerActive } from './reindex.js';
import { renderTrailLayer } from '../../mediaview/canvas/trail-layer.js';
import { _pointInPoly, _polyPoints } from '../../shape-editor/geometry.js';
import { normalizePolygon } from '../../core/polygon-source.js';
import { _makeLabelVisibleFn } from './_classfilter.js';
import { drawTrackBoxCanvas } from './_canvas-shapes.js';
import { resolveBoxStyle } from './_box-style.js';

// Bbox + trail visibility — flipped by the overlay-toggles pill bar
// (bboxes/trails). Module-scoped so the RAF redraw loop and the
// toggle handler share state without round-tripping through DOM
// attributes. Defaults mirror overlay-toggles.js (both on by default).
const _overlayVisibility = { showBboxes: true, showTrails: true };

export function setBboxOverlayVisibility({ showBboxes, showTrails }) {
  if (typeof showBboxes === 'boolean') _overlayVisibility.showBboxes = showBboxes;
  if (typeof showTrails === 'boolean') _overlayVisibility.showTrails = showTrails;
  _lbDrawDetections();
}

// I3 · `predicted`-source samples extend a track past the last
// real detection so the post-clip worker can express its grace
// window. On the video those frames are NOT a claim that the
// subject is still there — they're a tracker-internal "still
// trying". Capping the bbox draw at the LAST `detect`-source
// sample (with the small 0.05 s tolerance for sub-sample play
// positions) makes the on-video box vanish the instant the
// subject does, instead of pinning a stale outline in place
// during the grace window. The timeline panel still renders the
// predicted tail as its diagnostic hatch overlay.
function _lastDetectT(track) {
  const samples = track.samples || [];
  for (let i = samples.length - 1; i >= 0; i--) {
    const s = samples[i];
    if (
      s.source === undefined ||
      s.source === null ||
      s.source === 'detect' ||
      s.source === 'track'
    ) {
      return s.t;
    }
  }
  return -1;
}

export function _interpolateTrackAt(track, t) {
  const samples = track.samples || [];
  if (!samples.length) return null;
  const first = samples[0];
  if (t < first.t - 0.05) return null;
  const lastDetectT = _lastDetectT(track);
  if (lastDetectT < 0) return null;
  if (t > lastDetectT + 0.05) return null;
  let prev = first,
    next = samples[samples.length - 1];
  for (let i = 0; i < samples.length; i++) {
    if (samples[i].t <= t) prev = samples[i];
    if (samples[i].t >= t) {
      next = samples[i];
      break;
    }
  }
  if (prev === next || next.t === prev.t) {
    return { bbox: prev.bbox, score: prev.score, label: track.label };
  }
  const a = (t - prev.t) / (next.t - prev.t);
  const lerp = (k) => prev.bbox[k] + (next.bbox[k] - prev.bbox[k]) * a;
  return {
    bbox: { x1: lerp('x1'), y1: lerp('y1'), x2: lerp('x2'), y2: lerp('y2') },
    score:
      (prev.source === 'detect'
        ? prev.score
        : next.source === 'detect'
          ? next.score
          : track.best_score) ?? 0,
    label: track.label,
  };
}

function _firstSampleOfTrack(track) {
  const s = (track.samples || [])[0];
  if (!s) return null;
  return {
    bbox: s.bbox,
    score: s.source === 'detect' ? s.score : (track.best_score ?? 0),
    label: track.label,
  };
}

// Resolve which media element (video or still image) currently carries
// pixels, plus its natural (source) resolution. Returns null when
// neither is showing anything yet.
function _resolveActiveMedia() {
  const videoEl = byId('lightboxVideo');
  const imgEl = byId('lightboxImg');
  const usingVideo = videoEl && videoEl.style.display !== 'none' && videoEl.videoWidth > 0;
  const usingImage = imgEl && imgEl.style.display !== 'none' && imgEl.naturalWidth > 0;
  const media = usingVideo ? videoEl : usingImage ? imgEl : null;
  if (!media) return null;
  return {
    media,
    videoEl,
    usingVideo,
    natW: usingVideo ? videoEl.videoWidth : imgEl.naturalWidth,
    natH: usingVideo ? videoEl.videoHeight : imgEl.naturalHeight,
  };
}

// Size the canvas to the wrap's CSS box (accounting for devicePixelRatio)
// and compute the letterbox offset/scale that maps SOURCE pixel coords
// (tracks.json bbox space) onto the canvas.
function _prepCanvasTransform(cv, wrap, media, natW, natH) {
  const ctx = cv.getContext('2d');
  const wrapRect = wrap.getBoundingClientRect();
  const mediaRect = media.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  cv.style.width = wrapRect.width + 'px';
  cv.style.height = wrapRect.height + 'px';
  cv.width = Math.round(wrapRect.width * dpr);
  cv.height = Math.round(wrapRect.height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, wrapRect.width, wrapRect.height);
  const scale = Math.min(mediaRect.width / natW, mediaRect.height / natH);
  const renderedW = natW * scale,
    renderedH = natH * scale;
  const offX = (mediaRect.width - renderedW) / 2 + (mediaRect.left - wrapRect.left);
  const offY = (mediaRect.height - renderedH) / 2 + (mediaRect.top - wrapRect.top);
  return { ctx, offX, offY, scale };
}

// Interpolate every track's bbox to the current playback time. The RAF
// loop calls _lbDrawDetections every frame during play so the box moves
// smoothly; the seeked/pause/ended listeners call it on every scrub tick
// so the box snaps to the new position on pause + drag. _interpolateTrackAt
// returns null outside the track's [first.t, last.t] window — the track
// simply doesn't paint until its first sample is reached.
//
// Trails paint first so the bbox stroke sits on top — visually anchors
// the leading dot to the box.
function _drawTracksBranch(tracks, ctx, videoEl, usingVideo, geom, natW, natH, threshold, isVisible) {
  const { offX, offY, scale } = geom;
  const t = usingVideo ? videoEl.currentTime || 0 : null;
  if (_overlayVisibility.showTrails && t != null) {
    for (const tr of tracks.tracks) {
      if (!isVisible(tr.label)) continue;
      renderTrailLayer(ctx, tr, t, tr.color, offX, offY, scale);
    }
  }
  const camMasks = _resolveMaskPolygonsForCam(lbState.item?.camera_id);
  if (_overlayVisibility.showBboxes) {
    for (const tr of tracks.tracks) {
      if (!isVisible(tr.label)) continue;
      const sample = t == null ? _firstSampleOfTrack(tr) : _interpolateTrackAt(tr, t);
      if (!sample) continue;
      const status = _classifyTrackStatus(tr, sample, threshold);
      const masked = _isSampleMasked(sample, natW, natH, camMasks);
      const style = resolveBoxStyle(sample, tr.color, status, masked, tr._num);
      drawTrackBoxCanvas(ctx, sample, offX, offY, scale, style, masked);
    }
  }
}

// Legacy single-bbox fallback for clips with no sidecar yet (404 /
// pending fetch). Caller (_lbDrawDetections) already gates this on the
// reindex banner + playback state — see its comments for why.
function _drawLegacyFallback(ctx, geom, natW, natH, threshold, isVisible) {
  const { offX, offY, scale } = geom;
  const dets = (lbState.item.detections || [])
    .filter((d) => d && d.bbox && typeof d.bbox.x1 === 'number')
    .filter((d) => isVisible(d.label));
  if (!dets.length) return;
  const camMasks = _resolveMaskPolygonsForCam(lbState.item?.camera_id);
  for (const d of dets) {
    const c = colors[d.label] || colors.unknown;
    const sample = { bbox: d.bbox, score: d.score, label: d.label };
    const status = _classifyTrackStatus(null, sample, threshold);
    const masked = _isSampleMasked(sample, natW, natH, camMasks);
    const style = resolveBoxStyle(sample, c, status, masked, null);
    drawTrackBoxCanvas(ctx, sample, offX, offY, scale, style, masked);
  }
}

export function _lbDrawDetections() {
  const cv = byId('lightboxDetections');
  const wrap = byId('lightboxMediaWrap');
  if (!cv || !wrap || !lbState.item) return;
  const active = _resolveActiveMedia();
  if (!active) {
    _lbClearDetections();
    return;
  }
  const { media, videoEl, usingVideo, natW, natH } = active;
  const geom = _prepCanvasTransform(cv, wrap, media, natW, natH);
  const { ctx } = geom;

  const tracks = lbState.item._tracks;
  const haveTracks = tracks && Array.isArray(tracks.tracks) && tracks.tracks.length > 0;
  const sidecarFetched = tracks !== undefined;
  const sidecarEmpty = !!(tracks && Array.isArray(tracks.tracks) && tracks.tracks.length === 0);
  // Per-clip spawn threshold (gates.min_confidence) wins over the
  // module constant so the dashed/solid styling reflects what the
  // worker's classifier actually used. Falls back to the constant
  // for older sidecars without the gates block.
  const spawnThreshold =
    tracks && tracks.gates && typeof tracks.gates.min_confidence === 'number'
      ? tracks.gates.min_confidence
      : _TRACK_SPAWN_SCORE;
  const isVisible = _makeLabelVisibleFn();

  if (haveTracks) {
    _drawTracksBranch(tracks, ctx, videoEl, usingVideo, geom, natW, natH, spawnThreshold, isVisible);
    return;
  }

  // Indexer ran and produced an empty sidecar → keep the canvas clean.
  // Showing the trigger-frame detection here would be a stationary,
  // mis-positioned box that pops in only on scrub, with no relationship
  // to where the subject actually was during the recorded clip. The
  // timeline panel surfaces the WHY (gate values + filter) so the
  // operator understands the empty state without a misleading box.
  if (sidecarFetched && sidecarEmpty) return;

  // Suppressed entirely while the reindex banner is active (avoids
  // staring at the same trigger-frame box for ~17 s) and during active
  // playback (the trigger bbox is one moment in time; painting it during
  // motion would lie about subject location). Pause / ended / still-
  // image branches paint the box back at the trigger position so the
  // user has SOMETHING to see before the indexer finishes.
  if (_isReindexBannerActive()) return;
  const isPlaying =
    usingVideo && !videoEl.paused && !videoEl.ended && (videoEl.currentTime || 0) > 0.05;
  if (isPlaying) return;
  if (!_overlayVisibility.showBboxes) return;

  _drawLegacyFallback(ctx, geom, natW, natH, spawnThreshold, isVisible);
}

// Ground point = bottom-center of bbox. A subject is considered
// inside an exclusion mask when its feet land there — head-in-bush
// shouldn't trigger the mask filter when the body is in the open.
function _isSampleMasked(sample, natW, natH, masks) {
  if (!sample || !sample.bbox) return false;
  const cx = (sample.bbox.x1 + sample.bbox.x2) / 2;
  const cy = sample.bbox.y2;
  return _isPointInAnyMask(cx, cy, natW, natH, masks);
}

/**
 * Resolve the camera's exclusion-mask polygons with normalized
 * source_w/source_h via the shared core/polygon-source.js helper —
 * single source of truth across recorded lightbox, live-sim, and
 * the bbox renderer's per-sample masked test. Modern polygons carry
 * their own stamped dims; legacy unstamped polygons fall back to
 * the camera's substream resolution.
 */
export function _resolveMaskPolygonsForCam(camId) {
  if (!camId) return [];
  const cam = (state.cameras || []).find((c) => (c.id || '') === camId);
  if (!cam || !Array.isArray(cam.masks) || !cam.masks.length) return [];
  return cam.masks.map((m) => normalizePolygon(m, cam)).filter(Boolean);
}

/**
 * Test whether the source-frame point (px, py) lies inside any of
 * the camera's exclusion-mask polygons. Mask polygons may carry
 * their own source_w/source_h (when the editor was authored
 * against a substream snapshot); the test point is scaled into the
 * mask's own source space before the ray-cast, so a 2560×1440 bbox
 * coordinate maps correctly onto a mask drawn at 640×360.
 */
export function _isPointInAnyMask(px, py, srcW, srcH, masks) {
  if (!masks || !masks.length) return false;
  for (const m of masks) {
    const points = _polyPoints(m);
    if (points.length < 3) continue;
    const msrcW = (m && typeof m === 'object' && m.source_w) || srcW;
    const msrcH = (m && typeof m === 'object' && m.source_h) || srcH;
    const sx = msrcW > 0 && srcW > 0 ? msrcW / srcW : 1;
    const sy = msrcH > 0 && srcH > 0 ? msrcH / srcH : 1;
    if (_pointInPoly({ x: px * sx, y: py * sy }, points)) return true;
  }
  return false;
}

/**
 * Classify a track-or-detection sample against the spawn threshold.
 *
 *   confirmed — the SAMPLE's score is ≥ threshold right now.
 *   weak      — the track's best_score reached threshold at some
 *               point, but the CURRENT sample is below it.
 *   ghost     — best_score NEVER reached threshold (the track was
 *               kept alive entirely on tentative continuation).
 *
 * Legacy fallback path (single detection, no track): treat as
 * confirmed/weak based purely on score vs threshold — there's no
 * track history to derive a "best ever" from.
 */
export function _classifyTrackStatus(track, sample, threshold) {
  const t = typeof threshold === 'number' ? threshold : _TRACK_SPAWN_SCORE;
  const cur = sample && sample.score != null ? sample.score : null;
  const best = track && track.best_score != null ? track.best_score : null;
  // Track history available — three-tier classification.
  if (best != null) {
    if (best < t) return 'ghost';
    if (cur != null && cur < t) return 'weak';
    return 'confirmed';
  }
  // No track context — collapse to the two-tier legacy view.
  if (cur != null && cur < t) return 'weak';
  return 'confirmed';
}
