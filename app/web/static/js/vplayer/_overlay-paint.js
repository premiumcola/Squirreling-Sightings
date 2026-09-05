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
import { classColor } from '../core/class-colors.js';
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
import { clipReadiness, GEOM_PER_FRAME, triggerBoxVisible } from './_model/readiness.js';
import { liveTrackColor } from '../core/track-color.js';

/** Trail stroke width, in CSS pixels.
 *
 * A PLAIN NUMBER, because `buildTrailSvg` stamps the stroke with
 * `vector-effect="non-scaling-stroke"` — the browser then renders it at
 * this many SCREEN pixels whatever the viewBox is. The old value was
 * computed in SOURCE pixels (3 per 1000 of source width) and handed to
 * that same non-scaling stroke, so the two rules fought: the arithmetic
 * made the line thicker for a 4K camera, and the attribute then ignored
 * the scale it was compensating for. A 4K trail came out four times
 * heavier than a 1080p one on the same screen, for no reason anybody
 * chose. non-scaling-stroke already delivers the resolution
 * independence; the number just has to say what it means.
 */
const _TRAIL_W_PX = 2.5;

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
  const body = ((tracks && tracks.tracks) || [])
    .map((tr) => buildTrail(buildTrailPoints(tr, t), tr.color, { strokeWidth: _TRAIL_W_PX }))
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
 * They carry no track NUMBER — deliberately: the numbering belongs to
 * the sidecar's pass, and inventing one here would put a "#1" on the
 * picture that matches no lane and no row.
 *
 * THE COLOUR, THOUGH, IS THE CLASS. It used to be `liveTrackColor(null)`
 * — the neutral grey — on the argument that a trigger box claims no
 * identity. But the class IS known, and withholding it left one subject
 * painted three different ways on one screen: „Wieso nur 'n graue bbox
 * wenn ich pausiere??" — with a green „Vogel" lane above the rail and a
 * green „Vogel 52 %" row below it. `classColor` is the same palette
 * timeline/_basis.js gives a clip-aggregate lane, and for the same
 * reason: the class is a fact, the track identity is not. Grey now means
 * only what it always should have — an unknown class, or a masked box.
 */
function _triggerSamples(dets, src, masks) {
  return dets.map((d) => {
    const box = normalizeBox(d.bbox);
    const probe = box ? maskProbePoint(box) : null;
    return {
      // STATUS `ghost`, not the default. A sample with no status falls
      // through to `confirmed` — a solid, full-strength stroke, which
      // the status legend labels „Bestätigt". These boxes are the exact
      // opposite: one instant from the trigger frame, on a clip whose
      // re-analysis confirmed no track at all. Drawing the strongest
      // style available on the weakest evidence available is the same
      // defect as the green tick over „keine Spur bestätigt", one layer
      // down. `ghost` is dotted at 55 % with the „≈" marker, which is
      // what a single-frame guess actually looks like.
      raw: { ...d, track_num: null, status: 'ghost' },
      colour: (d.label && classColor(d.label)) || liveTrackColor(null),
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
  // WHICH GEOMETRY, asked of the readiness model — not of whether the
  // sidecar object happens to exist.
  //
  // „Wieso ist kein Rahmen in dem Vogel Video?" — because `st.tracks` was
  // tested for TRUTHINESS, and an empty sidecar is `{tracks: [], gates:
  // {…}}`, which is a perfectly truthy object. So a clip whose indexer
  // ran and confirmed nothing took the per-frame branch, got an empty
  // sample list out of it, and never reached the trigger branch at all —
  // while the banner directly underneath said „1 Auslöse-Kästen · nur
  // pausiert". The model and the painter disagreed about the same clip,
  // and the model was right.
  //
  // readiness.geometry is the single answer to "what can be drawn here",
  // which is exactly the question this is: GEOM_PER_FRAME means the
  // sidecar has real tracks, GEOM_TRIGGER means the trigger frame is all
  // there is. Nothing else may decide it.
  let samples = [];
  if (st.readiness.geometry === GEOM_PER_FRAME && st.tracks) {
    samples = _samplesAt(st.tracks, t, src, st.polys.masks, st.threshold);
  } else if (triggerBoxVisible(st.readiness, playing)) {
    samples = _triggerSamples(st.readiness.trigger, src, st.polys.masks);
  }
  renderBoxLayer(stage.layers.boxes, st.layers.bboxes ? samples : [], {
    frameSize: src,
    screenW: stage.rect().w,
    chrome: stage.chrome(),
  });
  // THE SILENT STATE, reported. „Ich hab im Player noch kein einziges Mal
  // eine Box gesehen" — said about clips that do carry geometry, on a
  // surface whose trails were painting the whole time. The `bboxes`
  // toggle persists across every clip and every session (it shares one
  // bucket with the Aufnahme-Settings checkbox), so one stray tap hides
  // every box on every clip from then on, and nothing anywhere says why
  // the picture is bare. The number of boxes WITHHELD is pushed out so
  // the row can offer them back.
  st.onHidden?.(st.layers.bboxes ? 0 : samples.length);
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
  // KEPT, so a repaint has something to repaint FROM. A live surface has
  // no `tracks` to re-derive a picture out of — the frame IS the source,
  // it arrives once per tick, and until now nothing held on to it. That
  // is half of the wipe described on `repaintAt` below: even a repaint
  // that wanted to redraw the boxes had nothing to draw.
  st.liveFrame = frame;
  const fs = frame.frameSize;
  if (fs && fs.w > 0 && fs.h > 0) st.liveSrc = fs;
  renderBoxLayer(stage.layers.boxes, st.layers.bboxes ? frame.detections : [], {
    frameSize: fs,
    screenW: stage.rect().w,
    chrome: stage.chrome(),
  });
  // The same report the recorded path makes, so the „N Rahmen
  // ausgeblendet" chip can appear on the surface it is most needed on.
  // Without it the safety net existed only where the boxes were already
  // working.
  st.onHidden?.(st.layers.bboxes ? 0 : (frame.detections || []).length);
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
    // The last frame a live/sim tick painted, so a repaint has a source.
    liveFrame: null,
    // Undefined tracks = "the sidecar request has not come back yet",
    // which is a third state and not the same as "there is none".
    readiness: clipReadiness(cfg.item, undefined),
    // Set by the caller; called with how many boxes this repaint had but
    // did not draw. See _paintRecorded.
    onHidden: null,
  };
  let lastT = 0;

  /**
   * Repaint from whichever source THIS surface actually has.
   *
   * THE BUG THIS FIXES, and it is the whole of „die Person im Video ist
   * nicht mit BBox umkreist":
   *
   * `repaintAt` used to call `_paintRecorded` unconditionally, including
   * on the live and simulation surfaces. There, `st.tracks` is null and
   * readiness is CLIP_PENDING, so `_paintRecorded` produces an empty
   * sample list and hands it to `renderBoxLayer` — which dutifully sets
   * `svg.innerHTML = ''`. It does not skip; it WIPES.
   *
   * And it ran constantly. Every simulation tick assigns a fresh base64
   * snapshot to `stage.img.src`; the `load` that follows fires
   * `_stage.js`'s refit, and the painter's refit listener called
   * `repaintAt`. So the order per tick was: paintLive draws the boxes →
   * the snapshot decodes → refit → the recorded painter erases them. The
   * boxes existed for a few milliseconds each tick and were never seen.
   *
   * The screenshot harness could not catch it: its simulation fixture
   * sends `snapshot: null`, so `img.src` is never reassigned, no `load`
   * fires, no refit, no wipe. Production and the harness differed in
   * exactly the one variable that triggers it.
   */
  const repaint = () => {
    if (cfg.flags.live) {
      if (st.liveFrame) _paintLiveFrame(stage, st, st.liveFrame);
      return;
    }
    const v = stage.video;
    _paintRecorded(stage, st, lastT, !!v && !v.paused && !v.ended);
  };

  const repaintAt = (t) => {
    lastT = Number.isFinite(t) ? t : 0;
    repaint();
  };

  // A layer host only knows where the picture is after a refit, and the
  // refit that matters — source dimensions arriving — happens AFTER the
  // first paint. Without this the zone canvas would be sized to the
  // pre-metadata box and never corrected.
  const offRefit = stage.onRefit(() => repaint());

  return {
    layers: () => ({ ...st.layers }),
    /** Report withheld boxes to whoever can offer them back. */
    onBoxesHidden: (fn) => {
      st.onHidden = fn;
      repaint();
    },
    /** The operator flipped a toggle. */
    setLayers: (next) => {
      Object.assign(st.layers, next || {});
      repaint();
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
