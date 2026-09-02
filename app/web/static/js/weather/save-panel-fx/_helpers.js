// ─── weather/save-panel-fx/_helpers.js ─────────────────────────────────
// Pure half of the save-panel weather backdrop: which effects a chip
// selection means, how often lightning may strike, and how one particle
// moves. No DOM, no timers, no canvas — everything here is a function of
// its arguments, so weather/_tests/save-panel-fx.test.js can pin the
// numbers that matter (above all the flash floor) without a browser.

// ── categories → effects ──────────────────────────────────────────────
// A 1:1 read of the chips the operator actually lit. Deliberately NOT
// "thunder implies rain": a storm that also brings rain is expressed by
// lighting BOTH chips, which is the multi-select case this panel exists
// for, and the union below then runs rain and lightning together.
export function fxModesFor(categories) {
  const set = new Set(categories || []);
  const thunder = set.has('thunder');
  const rising = set.has('thunder_rising');
  return {
    rain: set.has('heavy_rain'),
    snow: set.has('snow'),
    fog: set.has('fog'),
    lightning: thunder || rising,
    // "Gewitter zieht auf" on its own is a storm still building, not one
    // overhead — same flash, longer gaps between strikes.
    distant: rising && !thunder,
  };
}

// Nothing lit → no backdrop at all, and the caller unmounts entirely
// rather than running an idle loop over an empty particle list.
export function fxIsIdle(modes) {
  return !(modes.rain || modes.snow || modes.fog || modes.lightning);
}

// ── lightning cadence ─────────────────────────────────────────────────
// The floor is the accessibility contract, not a taste knob. A bright
// full-panel bloom is the one effect here that can genuinely harm a
// photosensitive viewer, and the recognised danger zone starts at 3
// flashes per second. 3200 ms between strikes caps this at 0.31 Hz —
// an order of magnitude below that line — and each strike carries
// exactly ONE luminance peak (see the ws-fx-strike keyframes), so no
// pair of peaks can ever sit closer than the floor.
export const FLASH_MIN_GAP_MS = 3200;
export const FLASH_SPREAD_MS = 6300;
// A building storm waits longer still.
export const FLASH_DISTANT_EXTRA_MS = 4200;
// Time to the FIRST strike after the panel opens. Shorter than the
// floor on purpose — it is the wait from a quiet panel to a single
// flash, not a gap between two of them, so it does not raise the flash
// rate; it only stops the effect going unnoticed for ten seconds.
export const FLASH_FIRST_MS = 1600;

// `rand` is injected so the test can pin both ends of the range.
export function nextFlashDelay(rand, distant) {
  const r = Math.min(Math.max(Number(rand) || 0, 0), 1);
  const spread = FLASH_SPREAD_MS + (distant ? FLASH_DISTANT_EXTRA_MS : 0);
  return Math.round(FLASH_MIN_GAP_MS + r * spread);
}

// ── particles ─────────────────────────────────────────────────────────
// Budget, not beauty: this runs in an editing panel on a box that is
// also decoding camera streams. The counts below are per panel area and
// hard-capped, and both kinds share the cap when both are lit.
export const FX_MAX_PARTICLES = 54;
export const FX_MIN_PARTICLES = 6;
const _AREA_PER_PARTICLE = { rain: 6000, snow: 11000 };

export function particleCountFor(kind, w, h, activeKinds = 1) {
  const area = Math.max(0, w) * Math.max(0, h);
  if (area < 1) return 0;
  const per = _AREA_PER_PARTICLE[kind] || _AREA_PER_PARTICLE.rain;
  const n = Math.round(area / per / Math.max(1, activeKinds));
  return Math.min(FX_MAX_PARTICLES, Math.max(FX_MIN_PARTICLES, n));
}

// Rain falls slightly off-vertical; the streak is drawn along the same
// axis, so one constant governs both the motion and the look.
export const FX_RAIN_SLANT = 0.22;
// Speeds are px per 60 Hz frame — stepParticle scales them by the real
// frame delta, so a 30 Hz phone and a 120 Hz tablet fall at the same
// rate in pixels per second.
const _SPEED = { rain: [5.4, 4.6], snow: [0.55, 0.95] };

export function seedParticle(kind, w, h, rand, atTop = false) {
  const [base, span] = _SPEED[kind];
  const p = {
    kind,
    x: rand() * Math.max(1, w),
    y: atTop ? -rand() * 40 : rand() * Math.max(1, h),
    vy: base + rand() * span,
  };
  if (kind === 'snow') {
    p.r = 1 + rand() * 1.4;
    p.drift = 0.25 + rand() * 0.5;
    p.sway = 0.012 + rand() * 0.02;
    p.phase = rand() * Math.PI * 2;
  } else {
    p.len = 8 + rand() * 10;
    // Two depth bands, drawn as two batched paths — the only cheap way
    // to get near/far contrast without a per-drop alpha and a per-drop
    // draw call.
    p.near = rand() < 0.45;
  }
  return p;
}

// Advances one particle and wraps it. `rand` re-randomises x on the
// wrap so a drop does not fall down the same column forever; injecting
// it keeps the whole step deterministic under test.
export function stepParticle(p, dt, w, h, rand = Math.random) {
  const s = Math.max(0, dt) / 16.6667;
  p.y += p.vy * s;
  if (p.kind === 'snow') {
    p.phase += p.sway * s;
    p.x += Math.sin(p.phase) * p.drift * s;
  } else {
    p.x -= p.vy * FX_RAIN_SLANT * s;
  }
  const span = Math.max(1, w);
  if (p.x < -20) p.x += span + 40;
  else if (p.x > span + 20) p.x -= span + 40;
  if (p.y - (p.len || p.r || 0) > h) {
    p.y = -(p.len || p.r || 0) - rand() * 24;
    p.x = rand() * span;
  }
  return p;
}
