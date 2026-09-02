// ─── weather/stats-chart/_pad.js ───────────────────────────────────────────
// How much of the wrapper is NOT plot. Pure arithmetic over label
// strings — no DOM, no colours, no samples.
//
// This used to be one frozen literal, `{ l: 42, r: 72, t: 12, b: 26 }`,
// shared by every chart at every width. On a 375 px phone that is 114 px
// of the 327 px wrapper — the plot got two thirds of the screen and the
// operator got two wide empty margins, which is exactly what was circled
// in red. Worse, neither number was right for what it reserved:
//
//   l: 42  reserved a lane for y-axis labels that the all-lines mode
//          does not draw AT ALL (buildYAxis only emits gridlines when no
//          single field is isolated), so on the panel's default view the
//          entire left rail was blank. In isolated mode it was too
//          SMALL instead: buildValueAxis right-aligns at `pad.l - 6`, so
//          "24000 m" (~42 px at 11 px) started at roughly x = −6 and got
//          clipped by the viewBox.
//   r: 72  reserved the widest threshold label lane on every chart, at
//          every width, whether or not a threshold was configured.
//
// So the rails are measured instead: the caller passes the strings that
// are actually about to be drawn, and each rail is sized to fit them.
// With nothing to draw a rail collapses to TICK_HALF, which is not zero
// because buildXTicks centres its time labels ON the rail edges — a "12:00"
// at x = pad.l needs half its width to its left or it clips.
//
// Everything here is exported for weather/_tests/stats-chart-pad.test.js.

import { niceAxisTicks, fmtAxisValue } from './_ticks.js';

// Vertical padding is unchanged and not width-dependent: `t` is breathing
// room over the highest curve, `b` is the one line of x-axis labels
// buildXTicks draws at `vbH - 8`.
export const PAD_T = 12;
export const PAD_B = 26;

/** What a chart falls back to when it has no rendered pad to report. */
export const PAD_FALLBACK = { l: 42, r: 72, t: PAD_T, b: PAD_B };

const Y_FONT = 11; // buildValueAxis
const EDGE_FONT = 10; // stats-thresholds.js, _multi.js::_anchors
const Y_GAP = 8; // its 6 px text offset, plus 2 px off the viewBox edge
const EDGE_GAP = 6; // its 4 px text offset, plus 2
// A rail is never narrower than this. buildXTicks centres its time
// labels ON the rail edges, and it CLAMPS each one back inside the
// viewBox (clampTickLabelX below), so this is breathing room and a
// guard against a curve's stroke sitting flush in the wrapper's rounded
// corner — not the thing that stops a label clipping.
const TICK_HALF = 16;
const RAIL_BUDGET = 0.34; // the two rails may not eat more of the width

// Per-character advances in em, calibrated against getBBox() on the real
// rendered ticks rather than guessed: at 11 px "00:00" measures 32.0 px
// (2.909 em) and at 10 px "▲ 60 km/h" measures 52.0 px, "3000 m" 38.4 px.
// Digits are the wide part of these labels — 0.65 em, not the 0.58 em a
// generic sans average suggests, and that 11 % gap was enough to leave
// the first x-tick flush against the wrapper's rounded corner.
//
// A real measurement would need a laid-out DOM and this runs before
// anything is drawn, so where it is wrong it is wrong high: a rail a few
// px wider than needed, never a clipped label.
const _DIGITS = new Set([...'0123456789']);
const _NARROW = new Set([' ', '.', ',', ':', "'", '′', '!', '|', 'i', 'j', 'l']);
const _WIDE = new Set(['▲', '▼', '°', '%', '—', '–', 'm', 'w', 'M', 'W']);

export function approxTextWidth(text, fontSize) {
  let em = 0;
  for (const ch of String(text ?? '')) {
    if (_NARROW.has(ch)) em += 0.3;
    else if (_DIGITS.has(ch)) em += 0.65;
    else if (_WIDE.has(ch)) em += 0.92;
    else em += 0.58;
  }
  return em * fontSize;
}

/**
 * Where a centred x-tick label may sit so it stays inside the viewBox.
 *
 * The first and last time labels are centred ON the plot edges, which is
 * exactly where the rails are narrowest. Reserving half a label on each
 * side would mean sizing the rails for the WIDEST format buildXTicks can
 * emit ("31. Aug" on the 30 d window, half again wider than "00:00") at
 * every window — paying the 30 d view's margin on the 1 h view. Nudging
 * the two outermost labels inward instead costs at most a couple of px
 * of offset from their own tick, and nothing ever clips.
 */
export function clampTickLabelX(x, label, fontSize, vbW) {
  const half = approxTextWidth(label, fontSize) / 2 + 1;
  if (!(vbW > half * 2)) return x;
  return Math.min(Math.max(x, half), vbW - half);
}

/**
 * The tick labels buildValueAxis will draw for a {lo, hi} in `unit`.
 *
 * Mirrors that function's own tick source (niceAxisTicks at target 4),
 * its formatter (fmtAxisValue) and its out-of-range skip, so the rail is
 * sized against the strings that actually reach the SVG.
 */
export function axisTickLabels(lo, hi, unit) {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [];
  const { ticks } = niceAxisTicks(lo, hi, 4);
  const span = hi - lo || 1;
  return ticks
    .filter((v) => v >= lo - span * 0.05 && v <= hi + span * 0.05)
    .map((v) => `${fmtAxisValue(v)}${unit ? ' ' + unit : ''}`);
}

/**
 * Padding for one render.
 *
 * `yLabels`    — strings buildValueAxis will right-align inside the left
 *                rail. Empty for the all-lines mode, which draws none.
 * `edgeLabels` — strings drawn just right of the plot (threshold labels).
 *                Empty when no threshold is configured.
 *
 * When the two rails together would exceed RAIL_BUDGET of the width, the
 * label lanes shrink proportionally to what each asked for, never below
 * TICK_HALF. That is the "shrink rather than reserve a fifth of the
 * screen" rule: a phone gives the labels what is left after the plot has
 * had two thirds, and a desktop, where the same labels are a rounding
 * error against 1300 px, gives them everything they asked for.
 */
export function statsChartPad({ width, yLabels = [], edgeLabels = [] } = {}) {
  const w = Number.isFinite(width) && width > 0 ? width : 0;
  const room = (labels, font, gap) =>
    labels.length
      ? Math.ceil(Math.max(...labels.map((s) => approxTextWidth(s, font)))) + gap
      : 0;
  let l = Math.max(TICK_HALF, room(yLabels, Y_FONT, Y_GAP));
  let r = Math.max(TICK_HALF, room(edgeLabels, EDGE_FONT, EDGE_GAP));
  const budget = Math.round(w * RAIL_BUDGET);
  if (l + r > budget) {
    const spare = Math.max(0, budget - TICK_HALF * 2);
    const asked = l - TICK_HALF + (r - TICK_HALF) || 1;
    const lAsk = l - TICK_HALF;
    l = TICK_HALF + Math.round((lAsk / asked) * spare);
    r = TICK_HALF + Math.max(0, spare - Math.round((lAsk / asked) * spare));
  }
  return { l, r, t: PAD_T, b: PAD_B };
}

// The pad a chart actually rendered with, stamped on its <svg> so a
// consumer that arrives LATER can ask rather than assume. storms/
// _detail.js paints its footage band on pointerenter, long after the
// render returned and with no handle on it; before this it read a
// module-level constant, which a per-render pad would have left stale.
export function padToAttr(pad) {
  return [pad.l, pad.r, pad.t, pad.b].map((n) => Math.round(n)).join(',');
}

export function padFromAttr(raw) {
  const n = String(raw ?? '')
    .split(',')
    .map(Number);
  if (n.length !== 4 || n.some((v) => !Number.isFinite(v))) return null;
  return { l: n[0], r: n[1], t: n[2], b: n[3] };
}
