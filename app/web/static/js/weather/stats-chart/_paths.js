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

export function buildLinePath(samples, key, x0, y0, w, h) {
  // Per-line normalisation: each parameter gets its own min/max so a 30
  // mm/h precipitation peak doesn't flatten the 0.5 cm/h snow line.
  // Null values split the trace into independent runs — Catmull-Rom is
  // applied per-run so a single missing sample doesn't smear an
  // interpolated curve across the gap. Runs of <6 points fall back to
  // straight L-segments because a 3- or 4-point spline tends to
  // overshoot wildly on sparse data.
  const vals = [];
  for (const s of samples) {
    const v = (s.values || {})[key];
    vals.push(typeof v === 'number' && isFinite(v) ? v : null);
  }
  const def = vals.filter((v) => v != null);
  if (def.length < 2) return null;
  let lo = Math.min(...def),
    hi = Math.max(...def);
  if (hi - lo < 1e-9) {
    lo -= 0.5;
    hi += 0.5;
  } // flat line: pin to mid-band
  const N = vals.length;
  // Group into contiguous runs of [x, y] points.
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
    const x = x0 + (N === 1 ? 0 : (i / (N - 1)) * w);
    const norm = (v - lo) / (hi - lo);
    const y = y0 + h - norm * h;
    cur.push([x, y]);
  }
  if (cur.length) runs.push(cur);
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
  return { path: d, lo, hi };
}
