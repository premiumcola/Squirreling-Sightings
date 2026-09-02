// ─── mediaview/_tests/live-detect-cadence.test.js ──────────────────────────
// The cadence arithmetic behind live-detect-poll.js's _scheduleNext, pinned
// at the boundaries its constants imply. Each of these numbers encodes a
// reproduced regression:
//   C73 · the per-stream floor (sub 500 ms / main 1000 ms)
//   P5  · the ceiling scales with the mode's inference count, so a 10 s 3×3
//         cycle is NOT clamped to 4 s (which would ask the camera for a new
//         frame before the previous answer is back)
//   C84 · the cycle EMA seeds on the first observation and the hold clamps
//         to [800, 1500]
// The point of the table is that a later edit to the constants or the
// arithmetic has to come here and say so out loud.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  _cadenceForCycle,
  _nextCycleEma,
  _holdMsFromEma,
  _TICK_FLOOR_SUB_MS,
  _TICK_FLOOR_MAIN_MS,
  _TICK_MAX_MS,
  _TICK_FACTOR,
  _HOLD_MS_CEILING,
  _HOLD_MS_FLOOR,
} from '../_live-detect-cadence.js';

test('the constants are the documented ones — a change here is a behaviour change', () => {
  assert.equal(_TICK_FLOOR_SUB_MS, 500);
  assert.equal(_TICK_FLOOR_MAIN_MS, 1000);
  assert.equal(_TICK_MAX_MS, 4000);
  assert.equal(_TICK_FACTOR, 1.2);
  assert.equal(_HOLD_MS_CEILING, 1500);
  assert.equal(_HOLD_MS_FLOOR, 800);
});

test('C73 · a sub-stream frame gets the 500 ms floor, main and unknown the 1 s floor', () => {
  assert.equal(_cadenceForCycle(100, 'sub', 1).floor, 500);
  assert.equal(_cadenceForCycle(100, 'main', 1).floor, 1000);
  // main_fallback and the first tick (no diag.frame_src yet) must both land
  // on the SAFER floor — an unhealthy camera is the case this protects.
  assert.equal(_cadenceForCycle(100, 'main_fallback', 1).floor, 1000);
  assert.equal(_cadenceForCycle(100, 'unknown', 1).floor, 1000);
  assert.equal(_cadenceForCycle(100, undefined, 1).floor, 1000);
});

test('a non-finite cycle (the very first tick) falls back to the floor as the cycle', () => {
  for (const bad of [NaN, undefined, Infinity, null]) {
    assert.equal(_cadenceForCycle(bad, 'sub', 1).cycleMs, 500, `cycle=${bad} on sub`);
    assert.equal(_cadenceForCycle(bad, 'main', 1).cycleMs, 1000, `cycle=${bad} on main`);
  }
});

test('a fast cycle is held at the floor, not at its own projection', () => {
  // 100 ms cycle → projected 120 ms, but the sub floor is 500.
  assert.equal(_cadenceForCycle(100, 'sub', 1).delay, 500);
  // Same cycle on main: the 1 s floor.
  assert.equal(_cadenceForCycle(100, 'main', 1).delay, 1000);
});

test('a mid-range cycle paces at round(cycle * 1.2)', () => {
  assert.equal(_cadenceForCycle(1000, 'sub', 1).delay, 1200);
  assert.equal(_cadenceForCycle(2000, 'main', 1).delay, 2400);
  // Rounding is Math.round, so .5 goes up.
  assert.equal(_cadenceForCycle(1387, 'sub', 1).delay, Math.round(1387 * 1.2));
});

test('P5 · a slow cycle is clamped to 4 s in the cheap mode …', () => {
  // 10 s cycle → projected 12 s, ceiling 4000 * 1 invoke.
  assert.equal(_cadenceForCycle(10_000, 'main', 1).delay, 4000);
});

test('P5 · … but NOT in an expensive one, where the ceiling scales with the invokes', () => {
  // The regression: clamping a 10 s 3×3 cycle (10 invokes → 40 s ceiling) to
  // 4 s asks the camera for a new frame before the previous answer is back.
  assert.equal(_cadenceForCycle(10_000, 'main', 10).delay, 12_000);
  // A 2×2-ish mode (4 invokes → 16 s ceiling) also leaves 12 s alone.
  assert.equal(_cadenceForCycle(10_000, 'main', 4).delay, 12_000);
  // Far enough out, even the scaled ceiling bites.
  assert.equal(_cadenceForCycle(60_000, 'main', 4).delay, 16_000);
});

test('the exact ceiling boundary: projected == maxDelay is not clamped below it', () => {
  // projected = round(cycle * 1.2) == 4000 exactly when cycle = 10000/3.
  const cycleMs = 4000 / _TICK_FACTOR;
  const { delay } = _cadenceForCycle(cycleMs, 'main', 1);
  assert.equal(delay, _TICK_MAX_MS);
});

test('the floor wins over the ceiling when the two would cross', () => {
  // Pathological but reachable: modeInvokes 0 would collapse the ceiling to
  // 0, and Math.min(0, max(floor, …)) would starve the loop. Guard the
  // documented order — max(floor, projected) is the inner term.
  const { delay } = _cadenceForCycle(100, 'sub', 1);
  assert.ok(delay >= _TICK_FLOOR_SUB_MS);
});

test('C84 · the EMA seeds on the first observation instead of starting at 0', () => {
  // A 0-initialised EMA would hand the very first tick an 800 ms hold that
  // has nothing to do with the camera's real cadence.
  assert.equal(_nextCycleEma(NaN, 700), 700);
  assert.equal(_nextCycleEma(undefined, 700), 700);
  assert.equal(_nextCycleEma(Infinity, 700), 700);
});

test('C84 · a seeded EMA pulls toward the new cycle at factor 0.4', () => {
  assert.equal(_nextCycleEma(1000, 2000), 0.4 * 2000 + 0.6 * 1000);
  // A repeated identical cycle is a fixed point.
  assert.equal(_nextCycleEma(900, 900), 900);
});

test('C84 · the EMA converges toward a step change without jumping to it', () => {
  let ema = _nextCycleEma(NaN, 500);
  assert.equal(ema, 500);
  // Camera slows to 2 s: the EMA must move up but stay under the new value.
  for (let i = 0; i < 5; i++) ema = _nextCycleEma(ema, 2000);
  assert.ok(ema > 500 && ema < 2000, `ema=${ema} should sit between 500 and 2000`);
});

test('C84 · the hold is clamp(2 * EMA, 800, 1500)', () => {
  // Mid-range: a healthy sub-stream cadence.
  assert.equal(_holdMsFromEma(500), 1000);
  assert.equal(_holdMsFromEma(600), 1200);
  // Floor: a very fast camera must still hold 800 ms, or the boxes blink.
  assert.equal(_holdMsFromEma(100), _HOLD_MS_FLOOR);
  assert.equal(_holdMsFromEma(0), _HOLD_MS_FLOOR);
  // Ceiling: a slow camera must not ghost a moving subject's box.
  assert.equal(_holdMsFromEma(2000), _HOLD_MS_CEILING);
});

test('C84 · the hold clamp boundaries are inclusive on both ends', () => {
  // 2 * 400 == 800 exactly — the floor, not below it.
  assert.equal(_holdMsFromEma(_HOLD_MS_FLOOR / 2), _HOLD_MS_FLOOR);
  // 2 * 750 == 1500 exactly — the ceiling, not above it.
  assert.equal(_holdMsFromEma(_HOLD_MS_CEILING / 2), _HOLD_MS_CEILING);
  // Just inside either edge stays unclamped.
  assert.equal(_holdMsFromEma(401), 802);
  assert.equal(_holdMsFromEma(749), 1498);
});
