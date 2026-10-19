// ─── shape-editor/draw-poly.js ─────────────────────────────────────────────
// Painting one committed polygon, in layers. drawShapes() calls each
// layer for EVERY polygon before the next layer starts, so handles end
// up above every body and every label — a label used to be painted
// after its polygon's vertices and covered the top-left one.
//
// The context is in CSS px (canvas.js sets the device-pixel transform),
// so radii and line widths below are what the eye sees on any screen.
import { shapeState } from '../core/state.js';
import { _polyPoints, _polyLabels, _polyCurves, segmentMidpoint } from './geometry.js';
import { toCss } from './view.js';

// Labels available for per-polygon scoping. Mirrors KNOWN_OBJECT_LABELS
// in schema.py — keep in sync if a new class joins the detector.
export const _SHAPE_LABEL_OPTS = [
  { k: 'person', l: 'Person' },
  { k: 'cat', l: 'Katze' },
  { k: 'bird', l: 'Vogel' },
  { k: 'car', l: 'Auto' },
  { k: 'dog', l: 'Hund' },
  { k: 'squirrel', l: 'Eichhörnchen' },
];

const VERTEX_R = 6;
const VERTEX_R_HOT = 8;
const MID_R = 4.5;
const BADGE_H = 20;
const BADGE_INSET = 10;

const _isCurve = (cp) => cp && Number.isFinite(cp.x) && Number.isFinite(cp.y);

// A quadratic bezier is affine-invariant, so mapping the control point
// with the same transform as the endpoints draws the same curve.
function _trace(ctx, layout, poly) {
  const pts = _polyPoints(poly).map((p) => toCss(layout, p));
  const curves = _polyCurves(poly);
  ctx.beginPath();
  ctx.moveTo(pts[0].x, pts[0].y);
  for (let i = 0; i < pts.length; i++) {
    const next = pts[(i + 1) % pts.length];
    if (_isCurve(curves[i])) {
      const c = toCss(layout, curves[i]);
      ctx.quadraticCurveTo(c.x, c.y, next.x, next.y);
    } else {
      ctx.lineTo(next.x, next.y);
    }
  }
  ctx.closePath();
}

export function paintBody(ctx, layout, { poly, color, emphasised }) {
  if (!_polyPoints(poly).length) return;
  _trace(ctx, layout, poly);
  ctx.fillStyle = color.replace('1)', '0.18)');
  ctx.strokeStyle = color;
  ctx.lineWidth = emphasised ? 3 : 2;
  ctx.lineJoin = 'round';
  ctx.fill();
  ctx.stroke();
}

// Text shortened with an ellipsis until it fits `maxW` CSS px.
export function fitText(text, maxW, measure) {
  if (measure(text) <= maxW) return text;
  let t = text;
  while (t.length > 1 && measure(`${t}…`) > maxW) t = t.slice(0, -1);
  return `${t.trimEnd()}…`;
}

// A badge never runs past its own polygon: on a phone the scope list
// otherwise spilled across the neighbouring mask. The full list is in
// the row under the canvas.
function _badge(ctx, x, y, text, fg, maxW) {
  const shown = fitText(text, maxW - 14, (t) => ctx.measureText(t).width);
  const w = ctx.measureText(shown).width + 14;
  ctx.fillStyle = 'rgba(0,0,0,.62)';
  ctx.beginPath();
  if (ctx.roundRect) ctx.roundRect(x, y, w, BADGE_H, 8);
  else ctx.rect(x, y, w, BADGE_H);
  ctx.fill();
  ctx.fillStyle = fg;
  ctx.fillText(shown, x + 7, y + 14);
}

function _scopeText(poly) {
  const lbls = _polyLabels(poly);
  if (!lbls.length) return { text: 'Alle Labels', scoped: false };
  const names = lbls.map((k) => (_SHAPE_LABEL_OPTS.find((o) => o.k === k) || { l: k }).l);
  return { text: names.join(', '), scoped: true };
}

// Name + label scope, tucked INSIDE the polygon's top-left corner and
// kept inside the frame — never on top of the corner vertex itself.
export function paintLabel(ctx, layout, { poly }) {
  const pts = _polyPoints(poly).map((p) => toCss(layout, p));
  if (!poly || !poly.label || !pts.length) return;
  const right = layout.ox + layout.w * layout.scale;
  const bottom = layout.oy + layout.h * layout.scale;
  const left = Math.min(...pts.map((p) => p.x)) + BADGE_INSET;
  const top = Math.min(...pts.map((p) => p.y)) + BADGE_INSET;
  const x = Math.max(layout.ox + 4, Math.min(left, right - 80));
  const y = Math.max(layout.oy + 4, Math.min(top, bottom - 2 * BADGE_H - 6));
  const maxW = Math.max(60, Math.min(right, Math.max(...pts.map((p) => p.x))) - x - 6);
  const scope = _scopeText(poly);
  ctx.font = '600 12px system-ui,sans-serif';
  _badge(ctx, x, y, poly.label, '#fff', maxW);
  ctx.font = '500 11px system-ui,sans-serif';
  _badge(ctx, x, y + BADGE_H + 3, scope.text, scope.scoped ? '#fbbf24' : '#e5e5e5', maxW);
}

// Bend handles. Hollow ring on a straight segment ("drag to bend"),
// filled disc on a curved one ("drag to reshape, double-tap to
// straighten"). Each sits ON the curve at t = 0.5 — the point the
// finger drags.
export function paintMidpoints(ctx, layout, { poly, color }) {
  const pts = _polyPoints(poly);
  const curves = _polyCurves(poly);
  for (let i = 0; i < pts.length; i++) {
    const m = toCss(layout, segmentMidpoint(pts[i], pts[(i + 1) % pts.length], curves[i]));
    const curved = _isCurve(curves[i]);
    ctx.beginPath();
    ctx.arc(m.x, m.y, MID_R, 0, Math.PI * 2);
    ctx.fillStyle = curved ? color : '#0a0a0a';
    ctx.fill();
    ctx.strokeStyle = curved ? '#ffffff' : color;
    ctx.lineWidth = 2;
    ctx.stroke();
  }
}

export function paintVertices(ctx, layout, { poly, color, kind, idx }) {
  const hot = shapeState.hoverVertex;
  const pts = _polyPoints(poly);
  for (let j = 0; j < pts.length; j++) {
    const isHot = hot && hot.kind === kind && hot.polyIdx === idx && hot.ptIdx === j;
    const p = toCss(layout, pts[j]);
    ctx.beginPath();
    ctx.arc(p.x, p.y, isHot ? VERTEX_R_HOT : VERTEX_R, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 2;
    ctx.stroke();
  }
}
