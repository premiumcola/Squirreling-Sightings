// ─── mediaview/canvas/trail-layer.js ───────────────────────────────────────
// Per-track motion trails — a polyline of bbox-center positions drawn
// behind the current bbox so the operator can read the subject's path
// at a glance. Shared between the Mediathek lightbox (recorded clips)
// and the Live-Simulation player (erk-sim) so both contexts use the
// same code path; the caller hands in a 2D context already transformed
// for letterboxing and the function never reaches back into the DOM.
//
// Coordinate convention: bbox samples are in SOURCE pixel coords
// (matches tracks.json on disk). Caller passes `offX`, `offY`, `scale`
// — the same letterbox math the bbox renderer uses — so the trail line
// lands on the SAME pixels as the bounding box that anchors it.

const TRAIL_MAX_POINTS = 20; // newest N centers — older drop out
const TRAIL_LINE_WIDTH = 2;
const TRAIL_HEAD_RADIUS = 3.5; // small dot at the current-time tip

function _bboxCenter(b) {
  return {
    x: (b.x1 + b.x2) * 0.5,
    y: (b.y1 + b.y2) * 0.5,
  };
}

// Lerp two bbox-center points at fractional position `a` ∈ [0,1].
function _lerpCenter(a, b, alpha) {
  return {
    x: a.x + (b.x - a.x) * alpha,
    y: a.y + (b.y - a.y) * alpha,
  };
}

/**
 * Build the trail point list for a single track up to playback time `t`.
 * Returns an array of {x, y} in SOURCE pixel coords, oldest → newest.
 * The newest point sits exactly at the interpolated position at `t`
 * so the trail meets the bbox cleanly. Returns [] when the track has
 * no samples or `t` is before the track's first sample.
 */
export function buildTrailPoints(track, t, maxPoints = TRAIL_MAX_POINTS) {
  const samples = (track && track.samples) || [];
  if (samples.length === 0) return [];
  const first = samples[0];
  if (t < first.t - 0.05) return [];

  const past = [];
  let prev = null,
    next = null;
  for (let i = 0; i < samples.length; i++) {
    const s = samples[i];
    if (s.t <= t) {
      past.push(_bboxCenter(s.bbox));
      prev = s;
    } else if (next == null) {
      next = s;
      break;
    }
  }

  // Append the interpolated head — the precise position at time `t`.
  // Without this, the trail ends at the most-recent sample center
  // rather than where the bbox actually sits, leaving a small gap.
  if (prev && next && next.t > prev.t) {
    const alpha = (t - prev.t) / (next.t - prev.t);
    past.push(_lerpCenter(_bboxCenter(prev.bbox), _bboxCenter(next.bbox), alpha));
  }

  if (past.length > maxPoints) {
    return past.slice(past.length - maxPoints);
  }
  return past;
}

/**
 * Render the trail polyline for a single track. Caller already
 * computed `points` via `buildTrailPoints`; this only handles the
 * letterbox transform + stroke styling.
 *
 * Older points fade toward transparent so the eye lands on the
 * current position. The colour is the track's deterministic palette
 * entry from tracks.json so multiple subjects in one clip stay
 * visually distinguishable.
 */
export function drawTrailPolyline(ctx, points, color, offX, offY, scale) {
  if (!ctx || !points || points.length < 2) return;
  const c = color || '#22c55e';
  ctx.save();
  ctx.lineWidth = TRAIL_LINE_WIDTH;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1];
    const b = points[i];
    // Fade ramp: oldest segment ≈ 0.10 alpha, newest ≈ 0.95.
    const segIdx = (i - 1) / Math.max(1, points.length - 2);
    const alpha = 0.1 + segIdx * 0.85;
    ctx.strokeStyle = c;
    ctx.globalAlpha = alpha;
    ctx.beginPath();
    ctx.moveTo(offX + a.x * scale, offY + a.y * scale);
    ctx.lineTo(offX + b.x * scale, offY + b.y * scale);
    ctx.stroke();
  }
  // Solid head dot at the current position. Caller may suppress
  // this by clipping at the bbox renderer's stroke, but a small
  // visible anchor reads well at a glance.
  const head = points[points.length - 1];
  ctx.globalAlpha = 1;
  ctx.fillStyle = c;
  ctx.beginPath();
  ctx.arc(offX + head.x * scale, offY + head.y * scale, TRAIL_HEAD_RADIUS, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

/**
 * Convenience entry that combines buildTrailPoints + drawTrailPolyline
 * for a single track. Callers that need to share the points (e.g. for
 * a tooltip "trail length: 14 samples" readout) can split the calls.
 */
export function renderTrailLayer(ctx, track, t, color, offX, offY, scale) {
  const pts = buildTrailPoints(track, t);
  drawTrailPolyline(ctx, pts, color, offX, offY, scale);
}

// ── SVG variant ─────────────────────────────────────────────────────────
// Live-Sim views (mediaview/live-detect.js, camedit/erk-sim/*) paint
// into <svg> overlays rather than <canvas>, but the trail VISUAL must
// match the recorded-clip view byte-for-byte so the user reads the
// same UI everywhere. Same ramp formula, same head-dot anchor —
// only the surface differs.
//
// `points` is the same {x, y} array buildTrailPoints produces, but
// expressed in the SVG's viewBox coordinate space (the SVG's own
// preserveAspectRatio handles letterboxing against the displayed
// element, so callers don't need offX/offY/scale here).

/**
 * Build the SVG markup for a trail polyline + leading-edge head dot.
 * Returns a string the caller can drop into `svg.innerHTML` alongside
 * other trail groups. `strokeWidth` should scale with the viewBox so
 * the on-screen thickness reads consistently across resolutions.
 *
 * `scoreScale` (0..1) dims the entire ramp uniformly — used by the
 * live-sim erk-sim to fade filtered/below-threshold tracks compared
 * to passing tracks. Pass 1 to disable the scaling.
 */
export function buildTrailSvg(points, color, strokeWidth = 3, scoreScale = 1) {
  if (!Array.isArray(points) || points.length < 2) return '';
  const c = color || '#22c55e';
  const lines = [];
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1];
    const b = points[i];
    const segIdx = (i - 1) / Math.max(1, points.length - 2);
    const alpha = ((0.1 + segIdx * 0.85) * scoreScale).toFixed(3);
    lines.push(
      `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" ` +
        `stroke="${c}" stroke-width="${strokeWidth}" ` +
        `stroke-opacity="${alpha}" stroke-linecap="round" ` +
        `vector-effect="non-scaling-stroke"/>`,
    );
  }
  // Solid head dot at the leading edge — anchors the eye to the
  // current track position even at a glance. Radius scales with
  // stroke so it reads as "trail tip" rather than "stray bullet".
  const head = points[points.length - 1];
  const r = Math.max(strokeWidth + 1, strokeWidth * 1.5);
  lines.push(`<circle cx="${head.x}" cy="${head.y}" r="${r}" fill="${c}" />`);
  return lines.join('');
}
