// ─── shape-editor/canvas.js ────────────────────────────────────────────────
// Canvas drawing primitives + the rAF-driven pulse loop for the closing-
// point ring while a polygon is in progress. Imports geometry helpers
// for vertex extraction; never imports from persistence (keeps the
// dependency graph one-way).
import { byId } from '../core/dom.js';
import { shapeState } from '../core/state.js';
import {
  ZONE_STROKE, ZONE_FILL, MASK_STROKE, MASK_FILL,
} from '../core/zone-tokens.js';
import { _polyPoints, _polyLabels, _polyCurves } from './geometry.js';

// Labels available for per-polygon scoping. Mirrors KNOWN_OBJECT_LABELS
// in schema.py — keep in sync if a new class joins the detector.
export const _SHAPE_LABEL_OPTS = [
  { k: 'person',   l: 'Person' },
  { k: 'cat',      l: 'Katze' },
  { k: 'bird',     l: 'Vogel' },
  { k: 'car',      l: 'Auto' },
  { k: 'dog',      l: 'Hund' },
  { k: 'squirrel', l: 'Eichhörnchen' },
];

export function getCanvasCtx(){ return byId('maskCanvas').getContext('2d'); }

// If the snapshot fails (camera offline, no recent frame, etc.) we
// still want a usable drawing surface — set the canvas to a fixed
// 1280×720 gray placeholder so clicks are mapped to a real coordinate
// space and the user can draw zones blind.
export function _maskCanvasFallback(){
  const canvas = byId('maskCanvas');
  if (!canvas) return;
  canvas.width = 1280;
  canvas.height = 720;
  canvas.style.width = '';
  canvas.style.height = '';
  const wrap = canvas.parentElement;
  if (wrap) wrap.style.aspectRatio = '1280/720';
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#222222';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#64748b';
  ctx.font = '14px system-ui,sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('Snapshot nicht verfügbar — Zonen können trotzdem gezeichnet werden.', canvas.width / 2, canvas.height / 2);
  ctx.textAlign = 'left';
}

function scaleForCanvas(el, img){
  // Internal canvas resolution = source resolution. canvasPoint() rescales
  // pointer events from CSS pixels (rect.width/height) to canvas pixels
  // (canvas.width/height) so polygon coordinates stay stable across any
  // display size. CSS handles the *display* sizing via inset:0 + the wrap's
  // natural-aspect height — no inline style.width/height needed here.
  const naturalW = img.naturalWidth || el.width || 1280;
  const naturalH = img.naturalHeight || el.height || 720;
  el.width = naturalW;
  el.height = naturalH;
  el.style.width = '';
  el.style.height = '';
}

function drawPoly(ctx, poly, color, fillAlpha, emphasised, kind, idx){
  const pts = _polyPoints(poly);
  if (!pts.length) return;
  // C2 — segment-aware path. For each segment i (0..N-1, last wrapping
  // to pts[0]), curves[i] supplies an optional quadratic-bezier
  // control point. If present, the segment renders as a curve bending
  // toward the control point; otherwise it falls back to a straight
  // lineTo — matches the legacy behaviour for every existing zone.
  const curves = _polyCurves(poly);
  ctx.beginPath();
  ctx.moveTo(pts[0].x, pts[0].y);
  for (let i = 0; i < pts.length; i++){
    const pNext = pts[(i + 1) % pts.length];
    const cp = curves[i];
    if (cp && typeof cp === 'object' && Number.isFinite(cp.x) && Number.isFinite(cp.y)){
      ctx.quadraticCurveTo(cp.x, cp.y, pNext.x, pNext.y);
    } else {
      ctx.lineTo(pNext.x, pNext.y);
    }
  }
  ctx.closePath();
  ctx.fillStyle = color.replace('1)', `${fillAlpha})`);
  ctx.strokeStyle = color;
  // kr592 — slimmer stroke proportional to the smaller vertex handles
  // below. Emphasised (selected) 3 px, normal 2 px.
  ctx.lineWidth = emphasised ? 3 : 2;
  ctx.fill();
  ctx.stroke();
  // Vertex handles — filled circles in the polygon colour with a white
  // border. C1 — radius 5 (default) / 7 (hover), stroke 1.5 px. Drawing
  // position is the ACTUAL point coordinate (no clamping); circles at
  // the canvas edge render half-clipped by the canvas pixel buffer,
  // which is the intended visual signal "point is on the edge". Hit-
  // test radius (geometry.js#_SHAPE_HIT_PX = 9) is decoupled from the
  // visual radius so touch taps stay comfortable.
  const hov = shapeState.hoverVertex;
  const isHov = (j) => hov && hov.kind === kind && hov.polyIdx === idx && hov.ptIdx === j;
  for (let j = 0; j < pts.length; j++){
    const r = isHov(j) ? 7 : 5;
    ctx.beginPath();
    ctx.arc(pts[j].x, pts[j].y, r, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }
  // C3 — segment midpoint handles. Hollow ring on straight segments
  // ("drag me to bend"); filled disc + dashed leader on curved
  // segments ("drag to reshape, dbl-click to straighten"). Skipped
  // while a new polygon is being placed so the user can drop points
  // without the editor competing visually. _hitMidpoint mirrors the
  // midpoint formula so click targeting stays aligned.
  if (!shapeState.points || shapeState.points.length === 0){
    for (let i = 0; i < pts.length; i++){
      const p0 = pts[i];
      const p1 = pts[(i + 1) % pts.length];
      const cp = curves[i];
      if (cp && Number.isFinite(cp.x) && Number.isFinite(cp.y)){
        const mx = 0.25 * p0.x + 0.5 * cp.x + 0.25 * p1.x;
        const my = 0.25 * p0.y + 0.5 * cp.y + 0.25 * p1.y;
        // Dashed leader from segment midpoint to control point so the
        // user sees what's pulling the curve.
        ctx.save();
        ctx.setLineDash([4, 3]);
        ctx.strokeStyle = color.replace('1)', '0.5)');
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(mx, my);
        ctx.lineTo(cp.x, cp.y);
        ctx.stroke();
        ctx.restore();
        // Filled disc at the segment midpoint.
        ctx.beginPath();
        ctx.arc(mx, my, 4, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 1.5;
        ctx.stroke();
        // Small marker at the control point itself.
        ctx.beginPath();
        ctx.arc(cp.x, cp.y, 3, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
      } else {
        const mx = (p0.x + p1.x) / 2;
        const my = (p0.y + p1.y) / 2;
        // Hollow ring — visually quieter than the curved-segment disc
        // so the user reads it as "tap to add a bend, not a vertex".
        ctx.beginPath();
        ctx.arc(mx, my, 3.5, 0, Math.PI * 2);
        ctx.fillStyle = '#0a0a0a';
        ctx.fill();
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
    }
  }
  if (poly && poly.label){
    const minX = Math.min(...pts.map(p => p.x));
    const minY = Math.min(...pts.map(p => p.y));
    const labelY = Math.max(20, minY);
    ctx.fillStyle = 'rgba(0,0,0,.6)';
    ctx.fillRect(minX, labelY - 22, Math.max(70, poly.label.length * 9), 20);
    ctx.fillStyle = '#fff';
    ctx.font = '600 13px system-ui,sans-serif';
    ctx.fillText(poly.label, minX + 6, labelY - 7);
    // Second badge below: which labels this polygon scopes (or "Alle").
    const lbls = _polyLabels(poly);
    const txt = lbls.length ? lbls.map(L => {
      const o = _SHAPE_LABEL_OPTS.find(x => x.k === L);
      return o ? o.l : L;
    }).join(', ') : 'Alle Labels';
    ctx.font = '500 11px system-ui,sans-serif';
    const w = Math.max(60, ctx.measureText(txt).width + 12);
    ctx.fillStyle = 'rgba(0,0,0,.55)';
    ctx.fillRect(minX, labelY, w, 18);
    ctx.fillStyle = lbls.length ? '#fbbf24' : 'rgba(255,255,255,.85)';
    ctx.fillText(txt, minX + 6, labelY + 13);
  }
}

export function drawShapes(){
  const img = byId('maskSnapshot'), canvas = byId('maskCanvas');
  if (!canvas) return;
  // Only re-scale to the snapshot when it actually loaded; if the
  // image is missing or broken we keep the placeholder dims set by
  // _maskCanvasFallback.
  const snapReady = img && img.src && img.complete && img.naturalWidth > 0;
  if (snapReady) scaleForCanvas(canvas, img);
  const ctx = getCanvasCtx();
  if (snapReady) ctx.clearRect(0, 0, canvas.width, canvas.height);
  // (when not ready, the gray placeholder already drawn by
  //  _maskCanvasFallback stays in the background)
  const pulseId = shapeState.pulse;
  // Zones land in green (Erkennungs-Zone), masks in red
  // (Ausschluss-Maske) — same colours every viewing context uses
  // via core/zone-tokens.js + 00-zone-tokens.css. The ZONE_FILL /
  // MASK_FILL tokens already carry the 0.18 alpha; drawPoly takes
  // a separate fillAlpha for the existing alpha-replace hook so
  // both fill colours line up at 0.18 on the canvas regardless
  // of caller-side overrides.
  (shapeState.zones || []).forEach((p, i) =>
    drawPoly(ctx, p, ZONE_STROKE, 0.18, pulseId === `zone:${i}`, 'zone', i));
  (shapeState.masks || []).forEach((p, i) =>
    drawPoly(ctx, p, MASK_STROKE, 0.18, pulseId === `mask:${i}`, 'mask', i));
  if (shapeState.points.length){
    ctx.beginPath();
    ctx.moveTo(shapeState.points[0].x, shapeState.points[0].y);
    shapeState.points.slice(1).forEach(p => ctx.lineTo(p.x, p.y));
    // Preview-stroke colour matches the committed-polygon colour for
    // the active mode so the user sees the upcoming shape's identity
    // while drawing. Vertex handles + the closing-point pulse below
    // stay neutral white so they remain visible against both blue
    // and red strokes.
    const previewColor = shapeState.mode === 'mask'
      ? MASK_STROKE
      : ZONE_STROKE;
    ctx.strokeStyle = previewColor;
    ctx.lineWidth = 2;
    ctx.setLineDash([7, 6]);
    ctx.stroke();
    ctx.setLineDash([]);
    // In-progress vertex handles. The first point gets a pulsing
    // ring once we have ≥3 points so the user knows clicking it
    // closes the polygon. The pulse is driven by Date.now() —
    // drawShapes is called by the rAF loop in _ensureShapePulseRaf
    // while we're in that state.
    const closable = shapeState.points.length >= 3;
    // C1 — in-progress vertex handles draw at the literal coordinate;
    // a point dropped right on the canvas edge renders as a half-disc
    // clipped by the pixel buffer (the intended "point is on the edge"
    // signal). The closing-point pulse ring BELOW is still clamped —
    // it's an affordance hint, not a coordinate.
    shapeState.points.forEach((p) => {
      const r = 5;
      ctx.beginPath();
      ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
      ctx.fillStyle = '#ffffff';
      ctx.fill();
      ctx.strokeStyle = '#1f2937';
      ctx.lineWidth = 1.5;
      ctx.stroke();
    });
    if (closable){
      const first = shapeState.points[0];
      const t = (Date.now() % 1200) / 1200;
      const phase = 0.5 - 0.5 * Math.cos(t * Math.PI * 2);
      const ringR = 16 + phase * 8;
      const alpha = 0.7 - phase * 0.5;
      const cw = canvas.width, chh = canvas.height;
      const clamp = (v, r, max) => Math.max(r, Math.min(max - r, v));
      const cx = clamp(first.x, 24, cw);
      const cy = clamp(first.y, 24, chh);
      ctx.beginPath();
      ctx.arc(cx, cy, ringR, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(34,197,94,${alpha.toFixed(2)})`;
      ctx.lineWidth = 3;
      ctx.stroke();
    }
    _ensureShapePulseRaf(closable);
  } else {
    _ensureShapePulseRaf(false);
  }
}

// rAF loop — runs only while a closable in-progress polygon is on
// screen. Redraws drawShapes() ~30 fps so the closing-point ring pulses
// smoothly.
let _shapePulseRaf = null;
function _ensureShapePulseRaf(active){
  if (active && !_shapePulseRaf){
    const tick = () => {
      // Stop if the editor closed or the in-progress polygon is gone.
      if (!shapeState.camera || (shapeState.points || []).length < 3){
        _shapePulseRaf = null;
        return;
      }
      drawShapes();
      _shapePulseRaf = requestAnimationFrame(tick);
    };
    _shapePulseRaf = requestAnimationFrame(tick);
  } else if (!active && _shapePulseRaf){
    cancelAnimationFrame(_shapePulseRaf);
    _shapePulseRaf = null;
  }
}
