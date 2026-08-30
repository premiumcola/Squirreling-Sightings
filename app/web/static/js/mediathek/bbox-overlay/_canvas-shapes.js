// ─── mediathek/bbox-overlay/_canvas-shapes.js ──────────────────────────────
// Canvas box-painting primitives, carved out of renderer.js so
// _lbDrawDetections stays an orchestrator rather than a painter. Style
// (dash / alpha / colors / label text) is resolved once by
// ./_box-style.js; this file only turns that + the letterboxed pixel
// rect into canvas draw calls.
import { MASKED_STROKE } from './_box-style.js';

function _strokeBox(ctx, x1, y1, w, h, style) {
  ctx.save();
  ctx.globalAlpha = style.alpha;
  ctx.strokeStyle = style.stroke;
  ctx.lineWidth = 2;
  ctx.setLineDash(style.dash);
  ctx.strokeRect(x1, y1, w, h);
  ctx.setLineDash([]);
  ctx.restore();
}

// Pill label above the box — "↓ #N · X %". Background uses the per-track
// color; text uses a DARKENED shade of that hue (never plain black) so
// the pill reads as "the person's color, intense fill, deep text" —
// matches the same family across the bbox + the characteristic card +
// the timeline.
function _drawLabelPill(ctx, x1, y1, style) {
  if (!style.text) return;
  const padX = 6,
    pillH = 18;
  ctx.font = '600 12px system-ui,-apple-system,"Segoe UI",Roboto,sans-serif';
  ctx.textBaseline = 'top';
  const tw = ctx.measureText(style.text).width;
  const pillY = Math.max(0, y1 - pillH - 2);
  ctx.save();
  ctx.globalAlpha = style.alpha;
  ctx.fillStyle = style.pillBg;
  ctx.fillRect(x1, pillY, tw + padX * 2, pillH);
  ctx.fillStyle = style.pillTextColor;
  ctx.fillText(style.text, x1 + padX, pillY + 3);
  ctx.restore();
}

// ⊘ corner badge — top-right of the box. Sits on its own small backdrop
// so it's readable against any video content. Drawn at full alpha
// (status alpha doesn't apply to the badge — it's a category indicator).
function _drawMaskedBadge(ctx, x2, y1) {
  const badge = 14;
  const bx = x2 - badge - 2;
  const by = y1 + 2;
  ctx.save();
  ctx.fillStyle = 'rgba(0,0,0,0.72)';
  ctx.beginPath();
  ctx.arc(bx + badge / 2, by + badge / 2, badge / 2 + 1, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = MASKED_STROKE;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.arc(bx + badge / 2, by + badge / 2, badge / 2 - 1, 0, Math.PI * 2);
  ctx.stroke();
  const r = badge / 2 - 2;
  const cxBadge = bx + badge / 2;
  const cyBadge = by + badge / 2;
  const off = r / Math.SQRT2;
  ctx.beginPath();
  ctx.moveTo(cxBadge - off, cyBadge - off);
  ctx.lineTo(cxBadge + off, cyBadge + off);
  ctx.stroke();
  ctx.restore();
}

/**
 * Paint one track/detection sample as a canvas box + pill (+ masked
 * badge). `style` comes from ./_box-style.js resolveBoxStyle().
 */
export function drawTrackBoxCanvas(ctx, sample, offX, offY, scale, style, masked) {
  const b = sample.bbox;
  const x1 = offX + b.x1 * scale,
    y1 = offY + b.y1 * scale;
  const x2 = offX + b.x2 * scale,
    y2 = offY + b.y2 * scale;
  const w = x2 - x1,
    h = y2 - y1;
  if (w <= 0 || h <= 0) return;
  _strokeBox(ctx, x1, y1, w, h, style);
  _drawLabelPill(ctx, x1, y1, style);
  if (masked) _drawMaskedBadge(ctx, x2, y1);
}
