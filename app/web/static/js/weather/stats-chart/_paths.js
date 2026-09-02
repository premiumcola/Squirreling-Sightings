// ─── weather/stats-chart/_paths.js ─────────────────────────────────────────
// Geometry only: sample array → SVG path string. No DOM, no colours.

// Catmull-Rom-to-Bezier converter. Returns an SVG path string for the
// run of points, smoothed via cubic Beziers whose control points come
// from the slope between each point's neighbours (uniform Catmull-Rom,
// scaled by `tension` to dampen overshoots — 0.5 keeps the curve close
// to the data without introducing wild bumps). Endpoints duplicate
// themselves as virtual "p0/p3" so the first and last segments don't
// flatten or kink. The caller is responsible for ensuring points come
// from a contiguous run (no nulls) — gaps must be split into separate
// runs by the caller.
export function catmullRomPath(pts, tension) {
  if (!pts || pts.length < 2) return '';
  const k = tension / 6;
  let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[i + 2] || pts[i + 1];
    const c1x = p1[0] + (p2[0] - p0[0]) * k;
    const c1y = p1[1] + (p2[1] - p0[1]) * k;
    const c2x = p2[0] - (p3[0] - p1[0]) * k;
    const c2y = p2[1] - (p3[1] - p1[1]) * k;
    d += ` C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  return d;
}

// Index → x-pixel mapper. Default is the legacy even i/(N-1) spacing.
// `opts.xValues` supplies an explicit numeric x per sample (the storm
// compare view passes relative minutes), mapped across the domain
// [xLo, xHi] — which defaults to the min/max of xValues but is normally
// passed in so several series of different lengths share one axis.
function _xMapper(opts, x0, w, N) {
  const xs = opts.xValues;
  if (!Array.isArray(xs) || xs.length !== N) {
    return (i) => x0 + (N === 1 ? 0 : (i / (N - 1)) * w);
  }
  const finite = xs.filter((v) => Number.isFinite(v));
  const xLo = Number.isFinite(opts.xLo) ? opts.xLo : Math.min(...finite);
  const xHi = Number.isFinite(opts.xHi) ? opts.xHi : Math.max(...finite);
  const xSpan = xHi - xLo || 1;
  return (i) => x0 + ((xs[i] - xLo) / xSpan) * w;
}

// Render contiguous runs of [x, y] points into one path string. Runs of
// <6 points fall back to straight L-segments because a 3- or 4-point
// spline tends to overshoot wildly on sparse data.
function _runsToPath(runs) {
  let d = '';
  for (const run of runs) {
    if (run.length >= 6) {
      d += (d ? ' ' : '') + catmullRomPath(run, 0.3);
    } else {
      d += (d ? ' M' : 'M') + run[0][0].toFixed(1) + ',' + run[0][1].toFixed(1);
      for (let j = 1; j < run.length; j++) {
        d += ' L' + run[j][0].toFixed(1) + ',' + run[j][1].toFixed(1);
      }
    }
  }
  return d;
}

// Per-field value range a line gets normalised against — factored out of
// buildLinePath so a second consumer (weather/_chart-annotations.js's
// curve-marker hit-test / redraw, which has to know exactly where a
// curve's pixel sits at a given sample to place or hit-test a marker on
// it) computes the SAME {lo, hi} the line was actually drawn against,
// rather than a second, potentially-drifting copy of the "flat line pins
// to mid-band" rule. `optLo`/`optHi` mirror buildLinePath's own lo/hi
// override.
// The field's TRUE extent in this window — the raw min/max, with none of
// the drawing rules applied. Anyone asking "how far did this actually
// move" must use this and not fieldValueRange: the latter pins a flat
// line to a ±0.5 band so it can be drawn mid-chart, and that band reads
// as a 1.0 swing that never happened. A dead-flat Schneefall curve
// looked like real snowfall to exactly that mistake.
export function fieldDataExtent(samples, key) {
  let lo = Infinity;
  let hi = -Infinity;
  let n = 0;
  for (const s of samples) {
    const v = (s.values || {})[key];
    if (typeof v !== 'number' || !isFinite(v)) continue;
    n += 1;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  return n < 2 ? null : { lo, hi };
}

export function fieldValueRange(samples, key, optLo, optHi) {
  const extent = fieldDataExtent(samples, key);
  if (!extent) return null;
  let lo = Number.isFinite(optLo) ? optLo : extent.lo;
  let hi = Number.isFinite(optHi) ? optHi : extent.hi;
  if (hi - lo < 1e-9) {
    lo -= 0.5;
    hi += 0.5;
  } // flat line: pin to mid-band
  return { lo, hi };
}

// `opts` (all optional, all defaulting to the pre-existing behaviour):
//   lo / hi          — force a shared value scale instead of per-line
//                      min/max. The storm compare view REQUIRES this:
//                      every line there is the same metric, so
//                      normalising each to its own extent would draw a
//                      12 mm/h cloudburst and a 3 mm/h shower as
//                      identical curves.
//   xValues / xLo / xHi — see _xMapper.
export function buildLinePath(samples, key, x0, y0, w, h, opts = {}) {
  // Per-line normalisation (default): each parameter gets its own
  // min/max so a 30 mm/h precipitation peak doesn't flatten the 0.5
  // cm/h snow line. Null values split the trace into independent runs —
  // Catmull-Rom is applied per-run so a single missing sample doesn't
  // smear an interpolated curve across the gap.
  const vals = [];
  for (const s of samples) {
    const v = (s.values || {})[key];
    vals.push(typeof v === 'number' && isFinite(v) ? v : null);
  }
  const range = fieldValueRange(samples, key, opts.lo, opts.hi);
  if (!range) return null;
  const { lo, hi } = range;
  const N = vals.length;
  const xAt = _xMapper(opts, x0, w, N);
  const runs = [];
  let cur = [];
  for (let i = 0; i < N; i++) {
    const v = vals[i];
    if (v == null) {
      if (cur.length) {
        runs.push(cur);
        cur = [];
      }
      continue;
    }
    const norm = (v - lo) / (hi - lo);
    cur.push([xAt(i), y0 + h - norm * h]);
  }
  if (cur.length) runs.push(cur);
  return { path: _runsToPath(runs), lo, hi };
}
