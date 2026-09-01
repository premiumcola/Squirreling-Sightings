// ─── stats-chart/_tests/paths-time-alignment.test.js ───────────────────
// Root-cause regression for the "drag-zoom lands on the wrong window"
// report: dragging a selection over the Wetterdaten-chart resolved to a
// different time range than the one visibly under the pointer, and the
// zoomed result ran out of data before the drawn line did.
//
// stats-chart/index.js's `_buildChartSvg` builds the LINE via
// buildLinePath, while _axes.js's buildXTicks and _hover.js's drag/hover
// math both position things by real elapsed TIME (tFirst..tLast,
// proportional). Before this fix, `_buildChartSvg` called buildLinePath
// with no `xValues`, so the line fell back to buildLinePath's own
// default: even spacing BY INDEX. Index spacing and time spacing only
// coincide when every sample is exactly as far (in time) from its
// neighbour as every other sample — true for a gap-free native-cadence
// window, false the moment a poll is missed, a service restarts, or
// _history_store.py's downsample() collapses a long window into
// count-based buckets. Whenever samples aren't uniformly spaced, the two
// systems disagreed about where a given timestamp sits on screen — which
// is exactly what let a drag "over the storm" resolve to a different,
// sometimes emptier, part of the buffer.
//
// stats-chart/_multi.js's own comment names this invariant: "the mapping
// minMin…maxMin → tFirst…tLast is linear and identical to the one
// buildLinePath uses" — true there because it always passes
// xValues/xLo/xHi. This test locks the main Wetter chart into the same
// contract.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildLinePath } from '../_paths.js';

// Mirrors the exact shape `_buildChartSvg` now builds: one ms timestamp
// per sample, plus the array's own first/last as xLo/xHi — the same
// tFirst/tLast every other piece of chart geometry (buildXTicks,
// _hover.js's _context) computes from `samples[0].ts` /
// `samples[last].ts`.
function timeAlignedMeta(samples, key, x0, w) {
  const xValues = samples.map((s) => new Date(s.ts).getTime());
  return buildLinePath(samples, key, x0, 0, w, 100, {
    xValues,
    xLo: xValues[0],
    xHi: xValues[xValues.length - 1],
  });
}

// Five samples, one contiguous run (<6 points → buildLinePath's straight
// L-segment fallback, not the Catmull-Rom smoother) so every plotted
// point's exact "x,y" pair appears verbatim in the path string and
// assertions don't have to reason about spline control points. Two
// 5-minute-cadence samples, then one large real-world gap (a missed
// poll / container restart), then three more — non-uniform exactly the
// way live weather history can be.
function samplesWithGap() {
  const start = Date.UTC(2026, 7, 24, 0, 0, 0);
  const ts = (ms) => new Date(ms).toISOString();
  const gapStart = start + 5 * 60_000 + 6 * 60 * 60_000; // +6h gap after sample 1
  return [
    { ts: ts(start), values: { v: 0 } },
    { ts: ts(start + 5 * 60_000), values: { v: 1 } },
    { ts: ts(gapStart), values: { v: 2 } }, // idxAfterGap
    { ts: ts(gapStart + 5 * 60_000), values: { v: 3 } },
    { ts: ts(gapStart + 10 * 60_000), values: { v: 4 } },
  ];
}

const IDX_AFTER_GAP = 2;

function expectedY(samples, idx) {
  const vals = samples.map((s) => s.values.v);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const norm = (vals[idx] - lo) / (hi - lo);
  return (100 - norm * 100).toFixed(1);
}

test('with no xValues, buildLinePath spaces samples evenly by index (the documented default)', () => {
  const samples = samplesWithGap();
  const meta = buildLinePath(samples, 'v', 0, 0, 120, 100);
  assert.ok(meta);
  const N = samples.length;
  const expectedIndexX = ((IDX_AFTER_GAP / (N - 1)) * 120).toFixed(1);
  assert.match(
    meta.path,
    new RegExp(`(^|[ML])${expectedIndexX},${expectedY(samples, IDX_AFTER_GAP)}(\\s|$)`),
    'default mapping places the post-gap point at its INDEX position — this is the documented default other callers (sparklines) still rely on',
  );
});

test('with xValues (the fix), a sample right after a real time gap lands at its TIME position, not its index position', () => {
  const samples = samplesWithGap();
  const w = 120;
  const meta = timeAlignedMeta(samples, 'v', 0, w);
  assert.ok(meta);
  const N = samples.length;
  const tFirst = new Date(samples[0].ts).getTime();
  const tLast = new Date(samples[N - 1].ts).getTime();
  const tHere = new Date(samples[IDX_AFTER_GAP].ts).getTime();
  const timeX = ((tHere - tFirst) / (tLast - tFirst)) * w;
  const indexX = (IDX_AFTER_GAP / (N - 1)) * w;
  // The gap makes the two diverge by more than a few pixels on a 120 px
  // plot — proving this is not a rounding artefact.
  assert.ok(
    Math.abs(timeX - indexX) > 5,
    'fixture must actually exercise a case where time- and index-position disagree',
  );
  const y = expectedY(samples, IDX_AFTER_GAP);
  assert.match(
    meta.path,
    new RegExp(`(^|[ML])${timeX.toFixed(1)},${y}(\\s|$)`),
    'time-aligned mapping must place the post-gap point at its real elapsed-time position',
  );
  assert.doesNotMatch(
    meta.path,
    new RegExp(`(^|[ML])${indexX.toFixed(1)},${y}(\\s|$)`),
    'time-aligned mapping must NOT fall back to the old index position',
  );
});

test('a gap-free, uniformly-spaced window: time-aligned and index-based positions coincide', () => {
  // Sanity check that the fix is a no-op for the common case (no real
  // gap in the window) — the two mappings must agree here, which is
  // exactly why the bug was intermittent rather than constant.
  const start = Date.UTC(2026, 7, 24, 0, 0, 0);
  const samples = Array.from({ length: 10 }, (_, i) => ({
    ts: new Date(start + i * 5 * 60_000).toISOString(),
    values: { v: i },
  }));
  const w = 90;
  const indexMeta = buildLinePath(samples, 'v', 0, 0, w, 100);
  const timeMeta = timeAlignedMeta(samples, 'v', 0, w);
  assert.equal(timeMeta.path, indexMeta.path);
});
