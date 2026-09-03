// ─── mediathek/bbox-overlay/renderer.js ────────────────────────────────────
// Overlay renderer + per-track interpolation helpers. The MP4 is NEVER
// modified; this paints a separate canvas (trails) + SVG (boxes) on top
// of the media element. Track colours come from the deterministic
// tracks.json palette so multiple subjects in one clip get distinguishable
// strokes.
//
// This file is the ORCHESTRATOR — per-render setup + branch selection.
// The label-visibility gate lives in ./_classfilter.js; the SVG box
// painter in ./svg-boxes.js; shared box style/text resolution in
// ./_box-style.js — split out so this file and its functions stay under
// CLAUDE.md's size ceilings.
import { byId } from '../../core/dom.js';
import { state } from '../../core/state.js';
import { colors } from '../../core/icons.js';
import { _lbClearDetections } from '../../lightbox.js';
import { lbState } from '../state.js';
import { fittedRect } from '../../core/video-fit.js';
import { _TRACK_SPAWN_SCORE } from './_state.js';
import { _isReindexBannerActive } from './reindex.js';
import { renderTrailLayer } from '../../mediaview/canvas/trail-layer.js';
import { _pointInPoly, _polyPoints } from '../../shape-editor/geometry.js';
import { normalizePolygon } from '../../core/polygon-source.js';
import { _makeLabelVisibleFn } from './_classfilter.js';
import { clearBboxSvg, drawTrackBoxesSvg } from './svg-boxes.js';
// The interpolation and the three-tier status moved to core when a THIRD
// painter needed them — the same journey core/box-model.js made, and for
// the same reason: they are pure, and reaching them from anywhere else
// meant importing this module, which wires real DOM at load.
//
// IMPORTED under the old names and then exported as those same local
// bindings, rather than re-exported straight from core. `export { X }
// from './y'` does not bind X in this file's own scope, and
// _drawTracksBranch calls both — the exact trap this codebase has hit
// before and documents in mediaview/player/_transport.js. One import,
// one export of the same binding, no second path to get it wrong.
import {
  classifyTrackStatus as _classifyTrackStatus,
  interpolateTrackAt as _interpolateTrackAt,
} from '../../core/track-sampling.js';

// Kept exported: confidence-meter.js imports _interpolateTrackAt from
// here, and moving that call site is not this change's business.
export { _classifyTrackStatus, _interpolateTrackAt };

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
// (tracks.json bbox space) onto the canvas. Reuses core/video-fit.js's
// fittedRect() for the letterbox math — the SVG box layer (svg-boxes.js)
// needs the SAME rect, so resolving it via the shared helper instead of
// a second inline computation keeps the two surfaces from drifting.
function _prepCanvasTransform(cv, wrap, media, natW) {
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
  const fit = fittedRect(media);
  const scale = natW > 0 ? fit.w / natW : 1;
  const offX = fit.x + (mediaRect.left - wrapRect.left);
  const offY = fit.y + (mediaRect.top - wrapRect.top);
  return { ctx, offX, offY, scale };
}

// Interpolate every track's bbox to the current playback time. The RAF
// loop calls _lbDrawDetections every frame during play so the box moves
// smoothly; the seeked/pause/ended listeners call it on every scrub tick
// so the box snaps to the new position on pause + drag. _interpolateTrackAt
// returns null outside the track's [first.t, last.t] window — the track
// simply doesn't paint until its first sample is reached.
//
// Trails (canvas) paint first, boxes (SVG, same z-index but appended
// after in the DOM — see svg-boxes.js) on top — visually anchors the
// leading dot to the box.
function _drawTracksBranch(tracks, ctx, frame) {
  const { media, wrap, videoEl, usingVideo, geom, natW, natH, threshold, isVisible } = frame;
  const { offX, offY, scale } = geom;
  const t = usingVideo ? videoEl.currentTime || 0 : null;
  if (_overlayVisibility.showTrails && t != null) {
    for (const tr of tracks.tracks) {
      if (!isVisible(tr.label)) continue;
      renderTrailLayer(ctx, tr, t, tr.color, offX, offY, scale);
    }
  }
  const camMasks = _resolveMaskPolygonsForCam(lbState.item?.camera_id);
  const boxes = [];
  if (_overlayVisibility.showBboxes) {
    for (const tr of tracks.tracks) {
      if (!isVisible(tr.label)) continue;
      const sample = t == null ? _firstSampleOfTrack(tr) : _interpolateTrackAt(tr, t);
      if (!sample) continue;
      const status = _classifyTrackStatus(tr, sample, threshold);
      const masked = _isSampleMasked(sample, natW, natH, camMasks);
      boxes.push({ sample, trackColor: tr.color, status, masked, trackNum: tr._num });
    }
  }
  drawTrackBoxesSvg(media, wrap, natW, natH, boxes);
}

// Legacy single-bbox fallback for clips with no sidecar yet (404 /
// pending fetch). Caller (_lbDrawDetections) already gates this on the
// reindex banner + playback state — see its comments for why.
function _drawLegacyFallback(frame) {
  const { media, wrap, natW, natH, threshold, isVisible } = frame;
  const dets = (lbState.item.detections || [])
    .filter((d) => d && d.bbox && typeof d.bbox.x1 === 'number')
    .filter((d) => isVisible(d.label));
  if (!dets.length) {
    drawTrackBoxesSvg(media, wrap, natW, natH, []);
    return;
  }
  const camMasks = _resolveMaskPolygonsForCam(lbState.item?.camera_id);
  const boxes = dets.map((d) => {
    const sample = { bbox: d.bbox, score: d.score, label: d.label };
    return {
      sample,
      trackColor: colors[d.label] || colors.unknown,
      status: _classifyTrackStatus(null, sample, threshold),
      masked: _isSampleMasked(sample, natW, natH, camMasks),
      trackNum: null,
    };
  });
  drawTrackBoxesSvg(media, wrap, natW, natH, boxes);
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
  const geom = _prepCanvasTransform(cv, wrap, media, natW);
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
  const frame = {
    media,
    wrap,
    videoEl,
    usingVideo,
    geom,
    natW,
    natH,
    threshold: spawnThreshold,
    isVisible,
  };

  if (haveTracks) {
    _drawTracksBranch(tracks, ctx, frame);
    return;
  }
  _drawNoTracksBranch(frame, sidecarFetched, sidecarEmpty);
}

// No real tracks.json tracks for this clip — either the sidecar was
// fetched and came back empty, or it hasn't landed yet (legacy fallback
// territory). Each early-out clears the SVG box layer so a stale box
// from the previously-open item can't linger.
function _drawNoTracksBranch(frame, sidecarFetched, sidecarEmpty) {
  const { videoEl, usingVideo } = frame;
  // Indexer ran and produced an empty sidecar → keep the overlay clean.
  // Showing the trigger-frame detection here would be a stationary,
  // mis-positioned box that pops in only on scrub, with no relationship
  // to where the subject actually was during the recorded clip. The
  // timeline panel surfaces the WHY (gate values + filter) so the
  // operator understands the empty state without a misleading box.
  if (sidecarFetched && sidecarEmpty) {
    clearBboxSvg();
    return;
  }
  // Suppressed entirely while the reindex banner is active (avoids
  // staring at the same trigger-frame box for ~17 s) and during active
  // playback (the trigger bbox is one moment in time; painting it during
  // motion would lie about subject location). Pause / ended / still-
  // image branches paint the box back at the trigger position so the
  // user has SOMETHING to see before the indexer finishes.
  if (_isReindexBannerActive()) {
    clearBboxSvg();
    return;
  }
  const isPlaying =
    usingVideo && !videoEl.paused && !videoEl.ended && (videoEl.currentTime || 0) > 0.05;
  if (isPlaying) {
    clearBboxSvg();
    return;
  }
  if (!_overlayVisibility.showBboxes) {
    clearBboxSvg();
    return;
  }
  _drawLegacyFallback(frame);
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

