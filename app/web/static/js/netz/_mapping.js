// ─── netz/_mapping.js ──────────────────────────────────────────────────────
// E ↔ Schwelle. BIT-FOR-BIT MIRROR of app/app/thresholds/_apply.py —
// the same rule that binds camera_id.build_camera_id to buildCameraId.
//
// One integer per (camera, class): E ∈ [0, 100], "Empfindlichkeit".
// Bigger radius on the net = bigger E = more sensitive = more Meldungen.
// E = 50 is exactly the shipped factory behaviour for that class.
//
//   STEP        = 0.006                    // 1 E-Punkt = 0.6 Prozentpunkte
//   delta(E)    = (50 - E) * STEP          // E=0 → +0.30 strenger
//   spawn(l,E)  = clamp(SPAWN_ANCHOR[l] + delta, 0.25, 0.90)
//   push (l,E)  = clamp(PUSH_ANCHOR [l] + delta, 0.45, 0.98)
//   if push < spawn + 0.10: push = spawn + 0.10
//
// The anchors below are copied from settings/_consts.py
// (LABEL_THRESHOLD_DEFAULTS, TELEGRAM_PUSH_DEFAULTS) and
// tracker_core/_consts.py (TRACK_SPAWN_SCORE). tests/test_netz_mapping.py
// writes a fixture of all 101 E values × every class, and
// test_netz_mapping_mirror.py runs THIS file against it — so a drift on
// either side fails, rather than quietly producing two different nets.

export const STEP = 0.006;
export const E_FACTORY = 50;
export const E_MIN = 0;
export const E_MAX = 100;

export const SPAWN_FLOOR = 0.25;
export const SPAWN_CEIL = 0.9;
export const PUSH_FLOOR = 0.45;
export const PUSH_CEIL = 0.98;
export const MIN_GAP = 0.1;

// Mirror of LABEL_THRESHOLD_DEFAULTS. A label absent here falls back to
// TRACK_SPAWN_SCORE, the value the live loop actually spawns at.
const SPAWN_ANCHORS = { person: 0.45, cat: 0.55, bird: 0.45, squirrel: 0.45 };
const TRACK_SPAWN_SCORE = 0.5;

// Mirror of TELEGRAM_PUSH_DEFAULTS.labels[*].threshold. fox / hedgehog /
// marten / deer have NO entry — before THR-3 they resolved to 0.0 at the
// live gate, which is why a net axis is the only thing that will ever
// give them a per-camera value. They take spawn + 0.35 here.
const PUSH_ANCHORS = {
  person: 0.85,
  cat: 0.8,
  dog: 0.8,
  bird: 0.9,
  car: 0.85,
  squirrel: 0.8,
  motion: 0.0,
};

// Fixed, GLOBAL axis order. Never sorted by value — a polygon whose
// spokes reorder between two cameras cannot be read.
export const AXIS_ORDER = [
  'person',
  'cat',
  'dog',
  'bird',
  'squirrel',
  'fox',
  'hedgehog',
  'marten',
  'deer',
  'car',
  'motion',
];

// Quantise to 4 decimals, half-up. NOT Math.round on the raw value:
// Python's round() uses banker's rounding and would disagree on exact
// ties. floor(x*1e4 + 0.5)/1e4 is the same IEEE-754 sequence in both.
function q(x) {
  return Math.floor(x * 10000 + 0.5) / 10000;
}

function clamp(x, lo, hi) {
  return x < lo ? lo : x > hi ? hi : x;
}

/** Coerce anything to a valid E. Garbage becomes factory, never zero —
 *  zero is the strictest setting there is, and a parse failure must not
 *  silently mean "report nothing". */
export function clampE(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return E_FACTORY;
  return Math.round(clamp(n, E_MIN, E_MAX));
}

export function spawnAnchor(label) {
  const a = SPAWN_ANCHORS[label];
  return a === undefined ? TRACK_SPAWN_SCORE : a;
}

export function pushAnchor(label) {
  const a = PUSH_ANCHORS[label];
  return a === undefined ? spawnAnchor(label) + 0.35 : a;
}

export function deltaFor(e) {
  return (E_FACTORY - clampE(e)) * STEP;
}

export function spawnFor(label, e) {
  return q(clamp(spawnAnchor(label) + deltaFor(e), SPAWN_FLOOR, SPAWN_CEIL));
}

export function pushFor(label, e) {
  let raw = clamp(pushAnchor(label) + deltaFor(e), PUSH_FLOOR, PUSH_CEIL);
  const spawn = spawnFor(label, e);
  // Only reachable AFTER clamping — the two anchors are always at least
  // 0.10 apart, so the gap can close only when one of them hits a rail.
  if (raw < spawn + MIN_GAP) raw = spawn + MIN_GAP;
  return q(raw);
}

export function thresholdsFor(label, e) {
  return { spawn: spawnFor(label, e), push: pushFor(label, e) };
}

/** E from a radius, for the drag. The angle is locked; only distance
 *  moves, so this is the whole of the pointer→value conversion.
 *  Within ±2 of factory it snaps to factory: Werk must be exactly
 *  recoverable by feel. No other snap points — the operator asked for
 *  fine, not stepped. */
export function eFromRadius(dist, r) {
  if (!(r > 0)) return E_FACTORY;
  const raw = clampE(Math.round((100 * dist) / r));
  return Math.abs(raw - E_FACTORY) <= 2 ? E_FACTORY : raw;
}

/** Radius in px for an E on a chart of radius r. */
export function radiusForE(e, r) {
  return (clampE(e) / 100) * r;
}
