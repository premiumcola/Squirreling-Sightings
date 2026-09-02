// ─── weather/_tests/save-panel-fx.test.js ──────────────────────────────
// weather/save-panel-fx/_helpers.js — the pure half of the save panel's
// ambient weather backdrop: chip selection → effects, the lightning
// cadence, and how one particle moves. The DOM half (index.js's
// observers, _particles.js's canvas loop, _lightning.js's timer) needs a
// browser and is not stubbed here; what IS pinned below is the part a
// regression would hurt someone with — the flash floor.
import { test } from 'node:test';
import assert from 'node:assert/strict';

const {
  FLASH_DISTANT_EXTRA_MS,
  FLASH_MIN_GAP_MS,
  FLASH_SPREAD_MS,
  FX_MAX_PARTICLES,
  FX_RAIN_SLANT,
  fxIsIdle,
  fxModesFor,
  nextFlashDelay,
  particleCountFor,
  seedParticle,
  stepParticle,
} = await import('../save-panel-fx/_helpers.js');

// ── categories → effects ──────────────────────────────────────────────

test('each manual category drives exactly its own effect', () => {
  assert.deepEqual(fxModesFor(['heavy_rain']), {
    rain: true,
    snow: false,
    fog: false,
    lightning: false,
    distant: false,
  });
  assert.equal(fxModesFor(['snow']).snow, true);
  assert.equal(fxModesFor(['fog']).fog, true);
  assert.equal(fxModesFor(['thunder']).lightning, true);
  assert.equal(fxModesFor(['thunder_rising']).lightning, true);
});

test('thunder does NOT imply rain — the operator lights both chips for that', () => {
  assert.equal(fxModesFor(['thunder']).rain, false);
  const storm = fxModesFor(['thunder', 'heavy_rain']);
  assert.equal(storm.lightning, true);
  assert.equal(storm.rain, true);
});

test('a storm only building strikes on the longer cadence, one overhead does not', () => {
  assert.equal(fxModesFor(['thunder_rising']).distant, true);
  assert.equal(fxModesFor(['thunder']).distant, false);
  // Both lit: the nearer storm wins.
  assert.equal(fxModesFor(['thunder', 'thunder_rising']).distant, false);
});

test('nothing selected is idle — no backdrop is built at all', () => {
  assert.equal(fxIsIdle(fxModesFor([])), true);
  assert.equal(fxIsIdle(fxModesFor()), true);
  // A non-manual key nothing maps to must not switch anything on.
  assert.equal(fxIsIdle(fxModesFor(['front_passing'])), true);
  assert.equal(fxIsIdle(fxModesFor(['fog'])), false);
});

// ── the flash floor (the accessibility contract) ──────────────────────

test('no two strikes can ever fall closer than the 3.2 s floor', () => {
  for (const distant of [false, true]) {
    for (const r of [0, 0.001, 0.5, 0.999, 1]) {
      assert.ok(
        nextFlashDelay(r, distant) >= FLASH_MIN_GAP_MS,
        `rand=${r} distant=${distant} fell below the floor`,
      );
    }
  }
});

test('the fastest possible flash rate stays an order below 3 Hz', () => {
  const fastestHz = 1000 / nextFlashDelay(0, false);
  assert.ok(fastestHz < 0.5, `flash rate ${fastestHz} Hz is not well under 3 Hz`);
});

test('a garbage rand cannot shorten the gap', () => {
  for (const bad of [-5, 12, NaN, undefined, null, 'x']) {
    assert.ok(nextFlashDelay(bad, false) >= FLASH_MIN_GAP_MS);
    assert.ok(nextFlashDelay(bad, false) <= FLASH_MIN_GAP_MS + FLASH_SPREAD_MS);
  }
});

test('the delay spreads over the full range, and further for a distant storm', () => {
  assert.equal(nextFlashDelay(0, false), FLASH_MIN_GAP_MS);
  assert.equal(nextFlashDelay(1, false), FLASH_MIN_GAP_MS + FLASH_SPREAD_MS);
  assert.equal(
    nextFlashDelay(1, true),
    FLASH_MIN_GAP_MS + FLASH_SPREAD_MS + FLASH_DISTANT_EXTRA_MS,
  );
  assert.ok(nextFlashDelay(0.5, true) > nextFlashDelay(0.5, false));
});

// ── particle budget ───────────────────────────────────────────────────

test('the particle count scales with the panel but never passes the cap', () => {
  assert.ok(particleCountFor('rain', 520, 430) <= FX_MAX_PARTICLES);
  assert.equal(particleCountFor('rain', 4000, 4000), FX_MAX_PARTICLES);
  // Snow is sparser than rain over the same panel.
  assert.ok(particleCountFor('snow', 520, 430) < particleCountFor('rain', 520, 430));
});

test('rain and snow together share one budget rather than doubling it', () => {
  const solo = particleCountFor('rain', 520, 430, 1);
  const shared = particleCountFor('rain', 520, 430, 2);
  assert.ok(shared < solo, 'the shared budget must be smaller than the solo one');
  assert.ok(shared + particleCountFor('snow', 520, 430, 2) < solo + 12);
});

test('a panel with no layout yet gets no particles', () => {
  assert.equal(particleCountFor('rain', 0, 0), 0);
  assert.equal(particleCountFor('rain', -20, 430), 0);
});

// ── motion ────────────────────────────────────────────────────────────

const _rand = (v) => () => v;

test('rain falls and slants; the streak axis matches the motion', () => {
  const p = seedParticle('rain', 300, 200, _rand(0.5));
  const { x, y } = p;
  stepParticle(p, 16.6667, 300, 200, _rand(0.5));
  assert.ok(p.y > y, 'rain must fall');
  assert.ok(p.x < x, 'rain must slant');
  const fallen = p.y - y;
  assert.ok(Math.abs((x - p.x) / fallen - FX_RAIN_SLANT) < 1e-9);
});

test('snow falls slower than rain and drifts sideways', () => {
  const rain = seedParticle('rain', 300, 200, _rand(0.5));
  const snow = seedParticle('snow', 300, 200, _rand(0.5));
  assert.ok(snow.vy < rain.vy / 3, 'snow must be much slower than rain');
  const x0 = snow.x;
  let moved = false;
  for (let i = 0; i < 40; i += 1) {
    stepParticle(snow, 16.6667, 300, 200, _rand(0.5));
    if (snow.x !== x0) moved = true;
  }
  assert.ok(moved, 'snow must drift');
});

test('displacement follows the real frame delta, not the frame count', () => {
  const slow = seedParticle('rain', 300, 200, _rand(0.5));
  const fast = { ...slow };
  stepParticle(slow, 16.6667, 300, 200, _rand(0.5));
  stepParticle(slow, 16.6667, 300, 200, _rand(0.5));
  stepParticle(fast, 33.3334, 300, 200, _rand(0.5));
  assert.ok(Math.abs(fast.y - slow.y) < 1e-6, 'a 30 Hz frame must cover two 60 Hz frames');
});

test('a particle past the bottom is recycled above the panel, not lost', () => {
  const p = seedParticle('rain', 300, 200, _rand(0.5));
  p.y = 500;
  stepParticle(p, 16.6667, 300, 200, _rand(0.25));
  assert.ok(p.y < 0, 'the drop must come back in above the top edge');
  assert.ok(p.x >= 0 && p.x <= 300);
});

test('sideways drift wraps instead of piling up at the edge', () => {
  const p = seedParticle('snow', 300, 200, _rand(0.5));
  p.x = -25;
  stepParticle(p, 16.6667, 300, 200, _rand(0.5));
  assert.ok(p.x > 250, 'a flake off the left edge re-enters from the right');
});

test('seeding at the top places the particle above the panel', () => {
  const p = seedParticle('snow', 300, 200, _rand(0.5), true);
  assert.ok(p.y <= 0);
});
