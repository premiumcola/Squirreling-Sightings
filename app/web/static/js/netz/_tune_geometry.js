// ─── netz/_tune_geometry.js ─────────────────────────────────────────────────
// Ellipse geometry for the Erkennungsprofil's settings radar. Pure — no
// DOM, no imports — so it runs under plain `node --test`
// (_tests/tune-geometry.test.js) and both the renderer (_tune_radar.js)
// and the pointer layer (_tune_drag.js) compute from ONE source.
//
// THE RADAR IS DRAWN AT THE SIZE OF ITS BOX. "Da ist ja viel Freiraum …
// es ist so viel zu klein, man kann's gar nicht erkennen": a fixed
// 560 x 300 viewBox letterboxed inside whatever .netz-card-chart got —
// wide margins left and right on a squarer box, top and bottom on a
// wider one, and the ring never larger than the fixed ellipse. Now
// netz/_panel.js measures the box in px and the viewBox IS that size,
// 1 unit = 1 px, so the ring reaches as far as the box allows after
// reserving one label rail on each side (labelWidthFor + RING_GAP) and
// the top/bottom vertex's own hit disc (PAD_Y). The rails themselves
// take the FULL height — the axis labels never needed vertical room
// beyond half a rail row, which PAD_Y already covers (_tune_labels.js
// clamps the column to the viewBox).
//
// TUNE_W x TUNE_H is the fallback for a render before the box has a
// size (a hidden section, a test) — same numbers the panel shipped
// with, so nothing that only ever saw the fallback looks different.
//
// eFromRadius/radiusForE in _mapping.js are a bit-for-bit mirror of
// app/app/thresholds/_apply.py and are pinned by test_netz_mapping_mirror
// — they are deliberately NOT reused or extended here. The ellipse
// inverse below is local to the settings path.

export const TUNE_W = 560;
export const TUNE_H = 300;

// ── how much of the box the LABELS are allowed to keep ──────────────────
// The rail used to reserve a flat 96 + 12 + 4 = 112 px on EACH side, so a
// 355 px phone panel spent 63 % of its width on labels and left the ring
// an rx of 65: "es ist so viel zu klein, man kann's gar nicht erkennen".
//
// The reservation scales with the box now, between two bounds that come
// from the text rather than from taste:
//   * LABEL_MAX 92 — "Wildtier-Empfindlichkeit", the longest axis name,
//     breaks at its hyphen into "Empfindlichkeit", ~92 px at the 11 px
//     bold the labels are drawn in. Wider buys nothing: the box already
//     fits the longest unbreakable run in one line.
//   * LABEL_MIN 68 — below this even a short class name ("Eichhörnchen")
//     needs a third line, and the rail row cannot pay for one.
// The value keeps its own line UNDER the name (.netz-tlbl is a column),
// which is what lets the box be this narrow at all.
const LABEL_MIN = 68;
const LABEL_MAX = 92;
const LABEL_SHARE = 0.22;

// Ring → label gap. Small on purpose: "Labels näher an die Achsenenden".
// The leader line, not a wide gutter, is what ties a box to its spoke.
export const RING_GAP = 4;

// Vertical reservation: EXACTLY the 44 px hit disc (r = 22, _tune_radar
// .js's _vertexSvg) of a vertex at E 100 on the top or bottom spoke. Not
// a px more — the rails need no vertical room of their own (they are
// clamped to the viewBox in _tune_labels.js) and every px here is ring.
export const PAD_Y = 22;

// A box too small for its rails still draws SOMETHING recognisable.
const R_MIN = 24;

// Snap window around an axis's own default, so "back to Werk" is
// recoverable by feel — the equivalent of _mapping.js's factory snap.
const SNAP = 2;

/** Label box width for a chart `w` px wide — see the bounds above. */
export function labelWidthFor(w) {
  return Math.round(Math.max(LABEL_MIN, Math.min(LABEL_MAX, w * LABEL_SHARE)));
}

/**
 * The ring for a chart box of `width` x `height` px. Either dimension
 * missing or non-positive falls back to TUNE_W / TUNE_H.
 *
 * @returns {{w: number, h: number, cx: number, cy: number, rx: number,
 *            ry: number, labelW: number}} `w`/`h` are the viewBox the
 *          caller must emit; `labelW` is what the rails may use.
 */
export function radarGeometry({ width, height } = {}) {
  const w = width > 0 ? Math.round(width) : TUNE_W;
  const h = height > 0 ? Math.round(height) : TUNE_H;
  const labelW = labelWidthFor(w);
  return {
    w,
    h,
    labelW,
    cx: w / 2,
    cy: h / 2,
    rx: Math.max(R_MIN, w / 2 - labelW - RING_GAP),
    ry: Math.max(R_MIN, h / 2 - PAD_Y),
  };
}

/** Half-width of the ring at height `y` — how far out the ellipse
 *  actually reaches on that line. A label row near the top or the bottom
 *  can sit far inside the widest point, which is what pulls the boxes in
 *  towards their own spoke ends instead of parking every one of them on
 *  the same far-out column. */
export function ringHalfWidthAt(geo, y) {
  const dy = (y - geo.cy) / geo.ry;
  return dy * dy >= 1 ? 0 : geo.rx * Math.sqrt(1 - dy * dy);
}

/** Point on the ellipse for (axis index, radial fraction 0-1). Index 0
 *  points straight up, the rest run clockwise. */
export function tunePolar(i, n, frac, geo) {
  const a = -Math.PI / 2 + (2 * Math.PI * i) / n;
  return { x: geo.cx + Math.cos(a) * geo.rx * frac, y: geo.cy + Math.sin(a) * geo.ry * frac };
}

/** Pointer offset from the centre → E (0-100), normalised PER AXIS so the
 *  same visual distance reads the same E on the long and the short axis.
 *  A plain hypot() would make the vertical axes reach 100 sooner than the
 *  horizontal ones on an ellipse. */
export function eFromEllipse(dx, dy, geo, defaultE = null) {
  if (!(geo.rx > 0) || !(geo.ry > 0)) return 0;
  const frac = Math.hypot(dx / geo.rx, dy / geo.ry);
  const raw = Math.max(0, Math.min(100, Math.round(frac * 100)));
  if (defaultE !== null && Math.abs(raw - defaultE) <= SNAP) return defaultE;
  return raw;
}
