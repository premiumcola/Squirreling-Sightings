// ─── vplayer/timeline/_model.js ────────────────────────────────────────────
// PURE. Tracks in, geometry out. No DOM at all.
//
// This is deliberate, and it is the lesson of the file it replaces: the
// old timeline panel is 709 lines with a 328-line function because its
// arithmetic was never separated from its painting, so the arithmetic
// could only be checked by looking at it. Everything here is a number,
// and every rule below has a test.
//
// ONE FUNCTION SERVES BOTH SHAPES. A recorded clip is a fixed window
// [0, duration] with a known pre- and post-roll. A live surface is a
// rolling window ending at `now`, and the same lanes fall out of the
// same code with a different window — which is what stops live and
// recorded growing two timelines that drift apart.
//
// WHAT IS PORTED FROM timeline-panel.js: the four-bucket per-sample
// classifier. The weak / predicted / masked segment textures are the
// ONLY place a viewer learns why a bar is dashed, and they are easy to
// drop in a rewrite because nothing else references them.
//
// WHAT IS DELIBERATELY NOT PORTED: the greedy mini-row packer and the
// two-tier top/bottom band. The new lane is one row per object, which
// the packer exists to avoid needing.

import { normalizeBox, maskProbePoint, pointInAnyMask } from '../_geometry.js';

/** Sample sources that mean "the detector actually saw this". */
const _DETECTED = new Set(['detect', 'track']);

/**
 * One sample → one of four buckets, in precedence order.
 *
 * masked    the subject is standing in an exclusion mask
 * predicted the tracker carried the box forward without a detection
 * weak      detected, but under the spawn threshold
 * confirmed detected at or above it
 *
 * Masked wins over everything because it is a statement about the
 * PLACE, not the detection: a confirmed subject inside a mask is still
 * excluded, and painting it as confirmed would tell the operator their
 * mask is not working.
 */
export function classifySample(s, opts = {}) {
  if (!s) return 'confirmed';
  const box = normalizeBox(s.bbox);
  const masks = opts.masks;
  if (box && masks && masks.length) {
    const p = maskProbePoint(box);
    if (pointInAnyMask(p.x, p.y, opts.srcW, opts.srcH, masks)) return 'masked';
  }
  const src = s.source;
  const detected = src === undefined || src === null || _DETECTED.has(src);
  if (!detected) return 'predicted';
  const threshold = opts.threshold;
  if (typeof s.score === 'number' && typeof threshold === 'number' && s.score < threshold) {
    return 'weak';
  }
  return 'confirmed';
}

/**
 * Collapse per-sample classifications into contiguous runs, so the bar
 * paints one texture per run rather than one per sample.
 *
 * @returns {Array<{status:string, t0:number, t1:number}>}
 */
export function segmentTrack(samples, opts = {}) {
  const list = Array.isArray(samples) ? samples : [];
  if (!list.length) return [];
  const out = [];
  let status = classifySample(list[0], opts);
  let start = list[0].t;
  for (let i = 1; i < list.length; i++) {
    const s = list[i];
    const next = classifySample(s, opts);
    if (next !== status) {
      out.push({ status, t0: start, t1: s.t });
      status = next;
      start = s.t;
    }
  }
  out.push({ status, t0: start, t1: list[list.length - 1].t });
  return out;
}

/** A track's overall status: what its longest-lived segment says. */
function _trackStatus(segments) {
  if (!segments.length) return 'confirmed';
  const span = {};
  for (const s of segments) {
    span[s.status] = (span[s.status] || 0) + Math.max(0, s.t1 - s.t0);
  }
  // A track of instants (every segment zero-length) still has to answer,
  // so fall back to counting segments rather than returning nothing.
  const byCount = {};
  for (const s of segments) byCount[s.status] = (byCount[s.status] || 0) + 1;
  const total = Object.values(span).reduce((a, b) => a + b, 0);
  const table = total > 0 ? span : byCount;
  return Object.keys(table).sort((a, b) => table[b] - table[a])[0];
}

/** Build one lane from one track. Returns null for a track with no samples. */
function _laneFor(track, opts) {
  const samples = (track && track.samples) || [];
  if (!samples.length) return null;
  const segments = segmentTrack(samples, opts);
  const barT0 = samples[0].t;
  const barT1 = samples[samples.length - 1].t;
  return {
    trackNum: track._num == null ? null : track._num,
    label: track.label || '',
    colour: track.color || null,
    // The dot marks the FIRST detection — the moment the object
    // entered. A single-sample track keeps its dot and gets a
    // zero-length bar; dropping the lane would hide the detection
    // entirely, which is the opposite of what a one-frame subject
    // needs.
    dotT: barT0,
    barT0,
    barT1,
    status: _trackStatus(segments),
    segments,
  };
}

/**
 * Position on the rail as a fraction, always within [0, 1].
 *
 * Clamped rather than trusted: a post-roll longer than the clip, or a
 * sample timestamped past the duration the container reports, would
 * otherwise paint outside the rail — where the stage's overflow:hidden
 * silently eats it.
 */
export function pctOf(t, duration) {
  if (!(duration > 0) || !Number.isFinite(t)) return 0;
  return Math.min(1, Math.max(0, t / duration));
}

/**
 * Build the timeline model.
 *
 * @param {Array} tracks  tracks.json-shaped tracks, or the live buffer
 * @param {object} opts
 * @param {number} opts.duration    clip length in seconds (recorded)
 * @param {number} [opts.windowMs]  rolling window (live). When set, the
 *   window is right-anchored at `now` and duration is derived from it.
 * @param {number} [opts.now]       end of the rolling window, seconds
 * @param {number} [opts.preRoll]   recording_settings.pre_motion_seconds
 * @param {number} [opts.postRoll]  recording_settings.post_motion_seconds
 * @param {number} [opts.threshold] track spawn score
 * @param {Array}  [opts.masks]     exclusion polygons
 * @param {number} [opts.srcW]      source width, for the mask test
 * @param {number} [opts.srcH]      source height
 * @returns {object} the model
 */
export function buildTimelineModel(tracks, opts = {}) {
  const rolling = opts.windowMs > 0;
  const now = Number.isFinite(opts.now) ? opts.now : 0;
  const windowS = rolling ? opts.windowMs / 1000 : 0;
  const duration = rolling ? windowS : Number.isFinite(opts.duration) ? opts.duration : 0;
  const windowStart = rolling ? now - windowS : 0;

  const list = Array.isArray(tracks) ? tracks : [];
  const lanes = [];
  for (const track of list) {
    const lane = _laneFor(track, opts);
    if (lane) lanes.push(lane);
  }

  const shifted = rolling ? _toWindow(lanes, windowStart, windowS) : lanes;
  _sortLanes(shifted);

  const preRoll = Math.max(0, Math.min(duration, opts.preRoll || 0));
  // The post-roll band starts where it starts even if the clip was cut
  // short; clamping the START (not just the width) is what keeps a
  // post-roll longer than the remaining clip inside the rail.
  const postRoll = Math.max(0, Math.min(duration - preRoll, opts.postRoll || 0));

  return {
    duration,
    rolling,
    preRoll,
    postRoll,
    postRollT0: Math.max(preRoll, duration - postRoll),
    // The white marker sits at the first detection of any lane. With no
    // lanes — or no duration to place it on — it is suppressed rather
    // than pinned to zero, where it would read as "the event began
    // immediately".
    firstEventT: shifted.length && duration > 0 ? Math.min(...shifted.map((l) => l.dotT)) : null,
    lanes: shifted,
  };
}

/**
 * Re-base lanes onto the rolling window and evict what fell out of it.
 * A lane that started before the window is kept, with its bar clipped
 * to the window edge — an object still on screen must not vanish from
 * the strip just because it arrived a minute ago.
 */
function _toWindow(lanes, windowStart, windowS) {
  const out = [];
  for (const lane of lanes) {
    if (lane.barT1 < windowStart) continue;
    const shift = (t) => Math.min(windowS, Math.max(0, t - windowStart));
    out.push({
      ...lane,
      dotT: shift(lane.dotT),
      barT0: shift(lane.barT0),
      barT1: shift(lane.barT1),
      segments: lane.segments
        .filter((s) => s.t1 >= windowStart)
        .map((s) => ({ status: s.status, t0: shift(s.t0), t1: shift(s.t1) })),
    });
  }
  return out;
}

/**
 * Deterministic lane order: earliest first, then by track number, then
 * by label. A re-render that reshuffles rows makes a moving object look
 * like it jumped lanes, and two tracks starting on the same frame is
 * the common case, not the edge case.
 */
function _sortLanes(lanes) {
  lanes.sort((a, b) => {
    if (a.barT0 !== b.barT0) return a.barT0 - b.barT0;
    const an = a.trackNum == null ? Infinity : a.trackNum;
    const bn = b.trackNum == null ? Infinity : b.trackNum;
    if (an !== bn) return an - bn;
    return String(a.label).localeCompare(String(b.label));
  });
}
