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
// reserving exactly one label rail on each side (LABEL_W + LABEL_OFF_X
// + RING_GAP, from the label metrics rather than guessed, so the boxes
// cannot hang off the edge) and a small vertical pad for the top and
// bottom vertex's own hit disc. The rails themselves take the FULL
// height — the axis labels never needed vertical room beyond half a
// rail row, which PAD_Y already covers (_tune_labels.js clamps the
// column to the viewBox).
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

/** Label box width, and the gap between the ring and the rail. The
 *  rail's horizontal reservation is derived from these — the ring has
 *  to leave exactly this much room or the rail hangs off the viewBox. */
export const LABEL_W = 96;
export const LABEL_OFF_X = 12;
const RING_GAP = 4;

// Vertical reservation: the 44 px hit disc (r = 22, _tune_radar.js's
// _vertexSvg) of a vertex at E 100 on the top or bottom spoke, plus a
// hair — the smallest pad that keeps the disc inside the box.
export const PAD_Y = 24;

// A box too small for its rails still draws SOMETHING recognisable.
const R_MIN = 24;

// Snap window around an axis's own default, so "back to Werk" is
// recoverable by feel — the equivalent of _mapping.js's factory snap.
const SNAP = 2;

/**
 * The ring for a chart box of `width` x `height` px. Either dimension
 * missing or non-positive falls back to TUNE_W / TUNE_H.
 *
 * @returns {{w: number, h: number, cx: number, cy: number, rx: number,
 *            ry: number}} `w`/`h` are the viewBox the caller must emit.
 */
export function radarGeometry({ width, height } = {}) {
  const w = width > 0 ? Math.round(width) : TUNE_W;
  const h = height > 0 ? Math.round(height) : TUNE_H;
  const padX = LABEL_W + LABEL_OFF_X + RING_GAP;
  return {
    w,
    h,
    cx: w / 2,
    cy: h / 2,
    rx: Math.max(R_MIN, w / 2 - padX),
    ry: Math.max(R_MIN, h / 2 - PAD_Y),
  };
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
