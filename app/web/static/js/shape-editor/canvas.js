// ─── shape-editor/canvas.js ────────────────────────────────────────────────
// drawShapes() + the rAF-driven pulse loop for the closing-point ring
// while a polygon is in progress. The canvas buffer is its CSS size ×
// devicePixelRatio and every draw call is in CSS px — it used to be the
// 640 × 360 snapshot stretched to screen size, which is why lines and
// curves came out blurry. Polygon coordinates stay in frame units;
// view.js maps them.
import { byId } from '../core/dom.js';
import { shapeState } from '../core/state.js';
import { ZONE_STROKE, MASK_STROKE } from '../core/zone-tokens.js';
import { currentLayout, toCss } from './view.js';
import { paintBody, paintLabel, paintMidpoints, paintVertices } from './draw-poly.js';

function _sizedContext(canvas, layout) {
  const dpr = window.devicePixelRatio || 1;
  const bw = Math.round(layout.cssW * dpr);
  const bh = Math.round(layout.cssH * dpr);
  // Assigning width resets the context even to the same value — only
  // touch it when the size really changed.
  if (canvas.width !== bw) canvas.width = bw;
  if (canvas.height !== bh) canvas.height = bh;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, layout.cssW, layout.cssH);
  return ctx;
}

function _clipToFrame(ctx, layout) {
  ctx.beginPath();
  ctx.rect(layout.ox, layout.oy, layout.w * layout.scale, layout.h * layout.scale);
  ctx.clip();
}

// No snapshot (camera offline, no frame yet): the stage keeps its
// aspect and the user can still draw blind.
function _paintMissingSnapshot(ctx, layout) {
  if (shapeState.frameState !== 'missing') return;
  const w = layout.w * layout.scale;
  const h = layout.h * layout.scale;
  ctx.fillStyle = '#64748b';
  ctx.font = '13px system-ui,sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('Kein Snapshot — zeichnen geht trotzdem', layout.ox + w / 2, layout.oy + h / 2);
  ctx.textAlign = 'left';
}

function _layers() {
  const pulse = shapeState.pulse;
  const item = (kind, color) => (poly, idx) => ({
    poly,
    idx,
    kind,
    color,
    emphasised: pulse === `${kind}:${idx}`,
  });
  return [
    ...(shapeState.zones || []).map(item('zone', ZONE_STROKE)),
    ...(shapeState.masks || []).map(item('mask', MASK_STROKE)),
  ];
}

export function drawShapes() {
  const canvas = byId('maskCanvas');
  const layout = currentLayout();
  if (!canvas || !layout) return;
  const ctx = _sizedContext(canvas, layout);
  _paintMissingSnapshot(ctx, layout);
  const items = _layers();
  // Bodies and labels stay inside the frame (a strongly bent curve may
  // bulge past it); handles may not be clipped — an edge vertex has to
  // show its whole disc in the gutter to be grabbable.
  ctx.save();
  _clipToFrame(ctx, layout);
  items.forEach((it) => paintBody(ctx, layout, it));
  items.forEach((it) => paintLabel(ctx, layout, it));
  ctx.restore();
  const drawing = shapeState.points.length > 0;
  if (!drawing) items.forEach((it) => paintMidpoints(ctx, layout, it));
  items.forEach((it) => paintVertices(ctx, layout, it));
  if (drawing) _paintInProgress(ctx, layout);
  _ensureShapePulseRaf(shapeState.points.length >= 3);
}

function _paintInProgress(ctx, layout) {
  const pts = shapeState.points.map((p) => toCss(layout, p));
  ctx.beginPath();
  ctx.moveTo(pts[0].x, pts[0].y);
  pts.slice(1).forEach((p) => ctx.lineTo(p.x, p.y));
  // Preview stroke in the colour of the active mode, so the upcoming
  // shape reads as zone or mask while it is drawn; the handles stay
  // neutral white so they show against both.
  ctx.strokeStyle = shapeState.mode === 'mask' ? MASK_STROKE : ZONE_STROKE;
  ctx.lineWidth = 2;
  ctx.setLineDash([7, 6]);
  ctx.stroke();
  ctx.setLineDash([]);
  pts.forEach((p) => {
    ctx.beginPath();
    ctx.arc(p.x, p.y, 6, 0, Math.PI * 2);
    ctx.fillStyle = '#ffffff';
    ctx.fill();
    ctx.strokeStyle = '#1f2937';
    ctx.lineWidth = 2;
    ctx.stroke();
  });
  // From three points on, a pulsing ring around the first one says
  // "tap here to close".
  if (pts.length < 3) return;
  const t = (Date.now() % 1200) / 1200;
  const phase = 0.5 - 0.5 * Math.cos(t * Math.PI * 2);
  ctx.beginPath();
  ctx.arc(pts[0].x, pts[0].y, 14 + phase * 6, 0, Math.PI * 2);
  ctx.strokeStyle = `rgba(34,197,94,${(0.7 - phase * 0.5).toFixed(2)})`;
  ctx.lineWidth = 3;
  ctx.stroke();
}

// rAF loop — runs only while a closable in-progress polygon is on
// screen. Redraws drawShapes() so the closing-point ring pulses.
let _shapePulseRaf = null;
function _ensureShapePulseRaf(active) {
  if (active && !_shapePulseRaf) {
    const tick = () => {
      // Stop if the editor closed or the in-progress polygon is gone.
      if (!shapeState.camera || (shapeState.points || []).length < 3) {
        _shapePulseRaf = null;
        return;
      }
      drawShapes();
      _shapePulseRaf = requestAnimationFrame(tick);
    };
    _shapePulseRaf = requestAnimationFrame(tick);
  } else if (!active && _shapePulseRaf) {
    cancelAnimationFrame(_shapePulseRaf);
    _shapePulseRaf = null;
  }
}
