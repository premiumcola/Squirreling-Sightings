// ─── netz/_tune_labels.js ──────────────────────────────────────────────────
// Where an axis label goes on the settings radar, and what it looks like.
//
// Split out of _tune_radar.js when the per-class Meldeschwellen became
// axes on the SAME net — one net per camera, because "ich will nicht zwei
// Netze". That takes a card from 10 spokes to 13 (Werkstatt) or 15
// (Squirrel Town), and up to 21 on a camera whose Klassen-Filter is wide
// open.
//
// The old placement cannot survive that. It centred each 104 px label box
// on its own spoke: at 10 axes the spokes are 36° apart and the boxes
// already touch; at 15 they are 24° apart, which puts two boxes 74 px
// apart with 104 px of width to fit. The two spokes either side of the
// bottom are the worst case — they sit at the same height.
//
// So labels are no longer placed ON the circle. Each is parked on a
// vertical RAIL beside the chart, on the side its spoke points to, at its
// spoke's own height; the column is then de-collided top-down so no two
// boxes overlap, and a connector in the axis colour joins the label back
// to the spoke it belongs to. Standard treatment for dense radial labels,
// and it degrades gracefully — with 10 axes almost nothing moves.
//
// THE VIEWBOX STAYS 440 x 340 whatever the axis count. The panel's width
// is whatever its .cam-net-slot column gives it (the SVG scales down via
// width/height="100%" in CSS), so a wider viewBox would only shrink every
// glyph — the extra axes are paid for out of ROW HEIGHT on the rail, the
// one dimension that can actually give.
//
// This module owns no geometry of its own: it is handed the spoke
// endpoints _tune_radar.js already computed, which is what keeps the
// import one-way and the angle math single-sourced.

import { esc } from '../core/dom.js';

/** Label box width, and the gap between the ring and the rail. PAD_X in
 *  _tune_radar.js is derived from these — the ring has to leave exactly
 *  this much room or the rail hangs off the viewBox. */
export const LABEL_W = 96;
export const LABEL_OFF_X = 12;

// Row height on the rail: the natural 36 px while there is room, never
// below 22 (two 9 px lines plus leading). 21 axes = 11 per side = 29 px.
const ROW_MAX = 36;
const ROW_MIN = 22;
const EDGE_PAD = 8;

/** How tall one rail row may be, given `n` axes on a chart `h` high. */
export function labelRowHeight(n, h) {
  const perSide = Math.max(1, Math.ceil(n / 2));
  const room = (h - 2 * EDGE_PAD) / perSide;
  return Math.max(ROW_MIN, Math.min(ROW_MAX, room));
}

/** Push overlapping rows apart, in place, keeping their order.
 *
 *  Two passes: downward from the top so nothing sits closer than one row
 *  to its predecessor, then upward from the bottom so the tail cannot
 *  leave the viewBox. A third pass is unnecessary — `labelRowHeight`
 *  guarantees the column fits. */
function _spread(rows, rowH, h) {
  rows.sort((a, b) => a.sy - b.sy);
  const half = rowH / 2;
  let prev = half - rowH;
  rows.forEach((r) => {
    r.y = Math.max(r.sy, prev + rowH);
    prev = r.y;
  });
  let limit = h - half;
  for (let k = rows.length - 1; k >= 0; k -= 1) {
    rows[k].y = Math.min(rows[k].y, limit);
    limit = rows[k].y - rowH;
  }
}

/**
 * Lay the labels out on the two rails.
 *
 * @param {Array}  points  `[{axis, x, y}]` — one spoke ENDPOINT per axis,
 *                         in axis order, as computed by _tune_radar.js.
 * @param {object} geo     `{cx, cy, rx, ry}` of the ring.
 * @param {number} h       viewBox height.
 * @returns {{rows: Array, rowH: number}} rows carry `{axis, sx, sy, x, y,
 *          side}` — `sx/sy` the spoke end, `x/y` the label box anchor.
 */
export function placeLabels(points, geo, h) {
  const n = points.length;
  const rowH = labelRowHeight(n, h);
  const right = [];
  const left = [];
  points.forEach((p, i) => {
    // Index, not sign(x): with an odd axis count the spoke pointing
    // straight down has x === cx, and `>= cx` would pile both the top and
    // the bottom label onto the same rail.
    const row = { axis: p.axis, sx: p.x, sy: p.y, side: i < n / 2 ? 'r' : 'l' };
    (row.side === 'r' ? right : left).push(row);
  });
  _spread(right, rowH, h);
  _spread(left, rowH, h);
  right.forEach((r) => {
    r.x = geo.cx + geo.rx + LABEL_OFF_X;
  });
  left.forEach((r) => {
    r.x = geo.cx - geo.rx - LABEL_OFF_X - LABEL_W;
  });
  return { rows: [...right, ...left], rowH };
}

// The connector. It starts where the spoke ends, so the pair reads as one
// line rather than as a second decorative stroke — the design rule bans
// borders, not the leader that makes a label mean something.
function _leaderSvg(r) {
  const x2 = r.side === 'r' ? r.x - 3 : r.x + LABEL_W + 3;
  return (
    `<line x1="${r.sx.toFixed(1)}" y1="${r.sy.toFixed(1)}" x2="${x2.toFixed(1)}" ` +
    `y2="${r.y.toFixed(1)}" stroke="${esc(r.axis.color)}" stroke-width="1" opacity=".3"/>`
  );
}

function _boxSvg(r, rowH, interactive) {
  const { axis } = r;
  const tag = interactive ? 'button' : 'span';
  // Still a button when the axis is locked: the tap is how the operator
  // finds out WHY it is greyed out, and that is the one thing a greyed
  // control must be able to say.
  const attrs = interactive ? ` type="button" data-tune-axis-label="${esc(axis.key)}"` : '';
  const off = axis.locked ? ' is-off' : '';
  return (
    `<foreignObject x="${r.x.toFixed(1)}" y="${(r.y - rowH / 2).toFixed(1)}" ` +
    `width="${LABEL_W}" height="${rowH.toFixed(1)}">` +
    `<${tag} xmlns="http://www.w3.org/1999/xhtml" ` +
    `class="netz-tlbl netz-tlbl--${r.side}${off}"${attrs}>` +
    `<span class="netz-tlbl-n" style="color:${esc(axis.color)}">${esc(axis.label)}</span>` +
    `<span class="netz-tlbl-v">${esc(axis.display)}</span>` +
    `</${tag}></foreignObject>`
  );
}

/** Connectors first, then the boxes — the leader must never draw over
 *  the text it points at. */
export function labelsSvg(points, geo, h, interactive) {
  const { rows, rowH } = placeLabels(points, geo, h);
  return (
    rows.map((r) => _leaderSvg(r)).join('') +
    rows.map((r) => _boxSvg(r, rowH, interactive)).join('')
  );
}
