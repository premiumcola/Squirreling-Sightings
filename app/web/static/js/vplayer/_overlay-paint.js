// ─── vplayer/_overlay-paint.js ─────────────────────────────────────────────
// What actually gets DRAWN on the picture — boxes, trails and the
// camera's zone / mask polygons — and the one place that knows which of
// the four layers the operator has switched on.
//
// WHY THIS FILE EXISTS. Every piece below already existed and none of it
// was reached from this player. _stage.js built three layer hosts, and
// only `boxes` was ever painted, only on the live surfaces; a recorded
// clip mounted a four-way toggle row over three permanently empty
// layers. The operator's verdict named both halves of the same defect:
// „die buttons zur anwahl … haben keine funktion … bbox oder zones seh
// ich alles nicht". A control cannot show or hide what nothing draws,
// and a layer nothing draws into is invisible however it is toggled.
//
// NOTHING IS RE-DERIVED HERE. Per-sample interpolation and the
// three-tier status are core/track-sampling.js's `interpolateTrackAt`
// and `classifyTrackStatus` — the legacy painter's own two functions,
// moved to core by this change because a third painter finally needed
// them and they were parked inside a module that wires DOM at load. The
// trail ramp is canvas/trail-layer.js's `buildTrailPoints`, the polygon
// painter is canvas/zone-layer.js's `renderZoneLayer` and the polygons'
// authored source dims come from core/polygon-source.js. All of it is
// what the legacy player uses, so the two surfaces cannot drift apart —
// and core/box-model.js::resolveBox already documents the `masked`
// argument as "the recorded painter decides masking geometrically … and
// passes the answer in", which is exactly the caller this file is.
//
// COORDINATES ARE FREE. _stage.js pins every layer host to the
// letterboxed picture rect, so INSIDE a host the picture is the whole
// box: an SVG viewBox of the source size lands on it exactly, and the
// canvas fit rect is simply (0, 0, w, h). This file must never solve the
// letterbox a second time — doing it twice, slightly differently, is how
// a box ends up half a gutter off its subject.

import { state } from '../core/state.js';
import { normalizePolygon } from '../core/polygon-source.js';
import { renderZoneLayer } from '../mediaview/canvas/zone-layer.js';
import { buildTrailPoints } from '../mediaview/canvas/trail-layer.js';
import {
  classifyTrackStatus,
  interpolateTrackAt,
  TRACK_SPAWN_SCORE,
} from '../core/track-sampling.js';
import { normalizeBox } from '../core/box-model.js';
import { buildTrail, renderBoxLayer } from './_overlay-svg.js';
import { maskProbePoint, pointInAnyMask } from './_geometry.js';
import { clipReadiness, triggerBoxVisible } from './_model/readiness.js';
import { liveTrackColor } from '../core/track-color.js';

/** Trail stroke width, in source pixels per 1000 px of source width. */
const _TRAIL_W_PER_KPX = 3;

/** The camera's zone and mask polygons, each with its authored dims. */
function _camPolygons(camId) {
  const cam = (state.cameras || []).find((c) => (c.id || '') === camId);
  if (!cam) return { zones: [], masks: [] };
  const norm = (list) => (list || []).map((p) => normalizePolygon(p, cam)).filter(Boolean);
  return { zones: norm(cam.zones), masks: norm(cam.masks) };
}

/** The source pixel size of whichever element currently carries pixels. */
function _sourceSize(stage) {
  const m = stage.media;
  const w = m?.videoWidth || m?.naturalWidth || 0;
  const h = m?.videoHeight || m?.naturalHeight || 0;
  return w > 0 && h > 0 ? { w, h } : null;
}

/**
 * The sidecar tracks visible at time `t`, as painter records.
 *
 * `masked` is decided here rather than in the style table because it is
 * geometry, not a verdict: the subject's FEET (maskProbePoint) inside an
 * exclusion polygon. A masked box still paints — greyed and labelled
 * „gefiltert" — because "why was nothing detected here" is the question
 * the overlay exists to answer.
 *
 * Exported for its test. Everything below it touches a DOM, but this is
 * where the decisions live — which tracks are on screen at all, what
 * colour each carries, and which of them the mask swallowed.
 */
export function _samplesAt(tracks, t, src, masks, threshold) {
  const list = (tracks && tracks.tracks) || [];
  const out = [];
  for (const tr of list) {
    const sample = interpolateTrackAt(tr, t);
    if (!sample) continue;
    const box = normalizeBox(sample.bbox);
    const probe = box ? maskProbePoint(box) : null;
    out.push({
      raw: { ...sample, status: classifyTrackStatus(tr, sample, threshold), track_num: tr._num },
      colour: tr.color || null,
      masked: !!probe && pointInAnyMask(probe.x, probe.y, src.w, src.h, masks),
      trackNum: tr._num,
    });
  }
  return out;
}

/** Paint every visible track's trail into its own SVG layer. */
function _paintTrails(host, tracks, t, src, on) {
  if (!host) return;
  if (!on || !tracks) {
    host.innerHTML = '';
    return;
  }
  const width = Math.max(2, (src.w / 1000) * _TRAIL_W_PER_KPX);
  const body = ((tracks && tracks.tracks) || [])
    .map((tr) => buildTrail(buildTrailPoints(tr, t), tr.color, { strokeWidth: width }))
    .filter(Boolean)
    .join('');
  host.innerHTML = body
    ? `<svg viewBox="0 0 ${src.w} ${src.h}" preserveAspectRatio="xMidYMid meet">${body}</svg>`
    : '';
}

/**
 * Paint the polygons into a canvas sized to the layer host.
 *
 * The host is already the picture rect, so the fit rect renderZoneLayer
 * clips to is the whole canvas — see this file's header.
 */
function _paintZones(host, polys, src, on) {
  if (!host) return;
  const box = host.getBoundingClientRect();
  const show = { zones: on.zones ? polys.zones : [], masks: on.masks ? polys.masks : [] };
  if (!src || box.width <= 0 || box.height <= 0 || (!show.zones.length && !show.masks.length)) {
    host.innerHTML = '';
    return;
  }
  let cv = host.firstElementChild;
  if (!cv) {
    cv = document.createElement('canvas');
    host.appendChild(cv);
  }
  const dpr = window.devicePixelRatio || 1;
  cv.width = Math.round(box.width * dpr);
  cv.height = Math.round(box.height * dpr);
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  renderZoneLayer(cv, show, src.w, src.h, {}, { x: 0, y: 0, w: box.width, h: box.height });
}

/**
 * The trigger frame's own detections, as painter records.
 *
 * The fallback for every clip with no sidecar, which is most of them.
 * They carry no track number and no sidecar colour — deliberately: the
 * numbering and the palette belong to the sidecar's pass, and inventing
 * either here would put a "#1" on the picture that matches no lane and
 * no row. `liveTrackColor(null)` gives them the neutral fallback stroke,
 * so they read as "detected" without claiming an identity.
 */
function _triggerSamples(dets, src, masks) {
  return dets.map((d) => {
    const box = normalizeBox(d.bbox);
    const probe = box ? maskProbePoint(box) : null;
    return {
      raw: { ...d, track_num: null },
      colour: liveTrackColor(null),
      masked: !!probe && pointInAnyMask(probe.x, probe.y, src.w, src.h, masks),
      trackNum: null,
    };
  });
}

/**
 * One full repaint of a RECORDED clip at time `t`.
 *
 * Split out of mountOverlayPainter so that function stays under the
 * 60-line ceiling. `st` is the painter's own mutable box: the layer
 * switches, the sidecar, the spawn threshold, the polygons and the
 * readiness verdict for this clip.
 *
 * TWO GEOMETRIES, never mixed. A sidecar gives per-frame boxes that
 * follow the subject; without one the trigger frame's boxes are all
 * there is, and those are a single instant — so they show while the clip
 * is parked and vanish the moment it runs, rather than trailing a stale
 * rectangle behind a subject that has walked out of it.
 */
function _paintRecorded(stage, st, t, playing) {
  const src = _sourceSize(stage);
  if (!src) return;
  let samples = [];
  if (st.tracks) {
    samples = _samplesAt(st.tracks, t, src, st.polys.masks, st.threshold);
  } else if (triggerBoxVisible(st.readiness, playing)) {
    samples = _triggerSamples(st.readiness.trigger, src, st.polys.masks);
  }
  renderBoxLayer(stage.layers.boxes, st.layers.bboxes ? samples : [], {
    frameSize: src,
    screenW: stage.rect().w,
  });
  _paintTrails(stage.layers.trails, st.tracks, t, src, st.layers.trails);
  _paintZones(stage.layers.zones, st.polys, src, st.layers);
}

/**
 * One repaint from a LIVE / simulation frame.
 *
 * The frame's own size wins over the element's for BOTH overlays. A
 * simulation <img> fed base64 snapshots reports naturalWidth reliably in
 * Chrome and 0x0 in Safari for an MJPEG stream — the case zone-layer.js's
 * srcW/srcH override was added for. The boxes always used the backend's
 * frame_size; the polygons have to be measured against the same
 * reference frame, or the two overlays land in different places on
 * exactly the browser where it is hardest to notice.
 */
function _paintLiveFrame(stage, st, frame) {
  const fs = frame.frameSize;
  if (fs && fs.w > 0 && fs.h > 0) st.liveSrc = fs;
  renderBoxLayer(stage.layers.boxes, st.layers.bboxes ? frame.detections : [], {
    frameSize: fs,
    screenW: stage.rect().w,
  });
  _paintZones(stage.layers.zones, st.polys, st.liveSrc || _sourceSize(stage), st.layers);
}

/**
 * Mount the overlay painter for one open player.
 *
 * It owns the LAYER STATE — which of bboxes / trails / zones / masks is
 * on — because two owners is how a toggle and a painter end up
 * disagreeing. The overlay row pushes the operator's choice in through
 * setLayers; nothing else writes it.
 *
 * @param {object} stage  handle from _stage.js
 * @param {object} cfg    normalised config from _config.js
 * @returns {object|null} painter handle
 */
export function mountOverlayPainter(stage, cfg) {
  if (!stage || !cfg.flags.showOverlays) return null;
  const st = {
    layers: { ...cfg.overlays },
    polys: _camPolygons(cfg.item.camera_id),
    tracks: null,
    threshold: TRACK_SPAWN_SCORE,
    liveSrc: null,
    // Undefined tracks = "the sidecar request has not come back yet",
    // which is a third state and not the same as "there is none".
    readiness: clipReadiness(cfg.item, undefined),
  };
  let lastT = 0;

  const repaintAt = (t) => {
    lastT = Number.isFinite(t) ? t : 0;
    const v = stage.video;
    _paintRecorded(stage, st, lastT, !!v && !v.paused && !v.ended);
  };

  // A layer host only knows where the picture is after a refit, and the
  // refit that matters — source dimensions arriving — happens AFTER the
  // first paint. Without this the zone canvas would be sized to the
  // pre-metadata box and never corrected.
  const offRefit = stage.onRefit(() => repaintAt(lastT));

  return {
    layers: () => ({ ...st.layers }),
    /** The operator flipped a toggle. */
    setLayers: (next) => {
      Object.assign(st.layers, next || {});
      repaintAt(lastT);
    },
    /**
     * The recorded clip's sidecar landed — or came back absent, which is
     * the answer for most clips and the one the painter used to treat as
     * "draw nothing and say nothing".
     */
    setTracks: (data, opts = {}) => {
      st.tracks = data || null;
      st.readiness = clipReadiness(opts.item || cfg.item, data === undefined ? undefined : data);
      const gate = data?.gates?.min_confidence;
      st.threshold = typeof gate === 'number' ? gate : (opts.threshold ?? TRACK_SPAWN_SCORE);
      repaintAt(lastT);
    },
    /** What this clip's evidence amounts to, for the panel to render. */
    readiness: () => st.readiness,
    repaintAt,
    paintLive: (frame) => _paintLiveFrame(stage, st, frame),
    teardown: () => {
      offRefit?.();
      for (const host of Object.values(stage.layers || {})) {
        if (host) host.innerHTML = '';
      }
    },
  };
}
