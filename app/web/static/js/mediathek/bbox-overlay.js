// ─── mediathek/bbox-overlay.js ─────────────────────────────────────────────
// Stage 21 of the legacy.js → ES modules refactor — draws coloured
// detection rectangles + label pills over the active lightbox media.
// Bbox coords come from lbState.item.detections[].bbox in the original
// frame's pixel space; we scale them to the object-fit:contain
// rendered rectangle so they line up whether the media is letterboxed
// vertically or horizontally.
//
// The IIFE at the bottom wires three repaint triggers:
//   - <img> load (fires even for cached images)
//   - <video> loadedmetadata (so video boxes appear once dimensions known)
//   - window resize (RAF-debounced, only repaints while modal is visible)
import { byId } from '../core/dom.js';
import { colors, OBJ_LABEL } from '../core/icons.js';
import { _lbClearDetections } from '../lightbox.js';
import { lbState } from './state.js';

export function _lbDrawDetections(){
  const cv = byId('lightboxDetections');
  if (!cv || !lbState.item) return;
  const ctx = cv.getContext('2d');
  const videoEl = byId('lightboxVideo');
  const imgEl = byId('lightboxImg');
  const usingVideo = videoEl && videoEl.style.display !== 'none' && videoEl.videoWidth > 0;
  const usingImage = imgEl && imgEl.style.display !== 'none' && imgEl.naturalWidth > 0;
  const media = usingVideo ? videoEl : (usingImage ? imgEl : null);
  if (!media){ _lbClearDetections(); return; }
  const natW = usingVideo ? videoEl.videoWidth : imgEl.naturalWidth;
  const natH = usingVideo ? videoEl.videoHeight : imgEl.naturalHeight;
  const wrap = byId('lightboxMediaWrap');
  if (!wrap) return;
  const wrapRect = wrap.getBoundingClientRect();
  const mediaRect = media.getBoundingClientRect();
  // Size the canvas to cover the wrap; use DPR for crisp strokes.
  const dpr = window.devicePixelRatio || 1;
  cv.style.width = wrapRect.width + 'px';
  cv.style.height = wrapRect.height + 'px';
  cv.width  = Math.round(wrapRect.width * dpr);
  cv.height = Math.round(wrapRect.height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, wrapRect.width, wrapRect.height);
  const dets = (lbState.item.detections || []).filter(d => d && d.bbox && typeof d.bbox.x1 === 'number');
  if (!dets.length) return;
  // object-fit:contain inside the media element
  const scale = Math.min(mediaRect.width / natW, mediaRect.height / natH);
  const renderedW = natW * scale, renderedH = natH * scale;
  const offX = (mediaRect.width - renderedW) / 2 + (mediaRect.left - wrapRect.left);
  const offY = (mediaRect.height - renderedH) / 2 + (mediaRect.top - wrapRect.top);
  ctx.font = '600 12px system-ui,-apple-system,"Segoe UI",Roboto,sans-serif';
  ctx.textBaseline = 'top';
  for (const d of dets){
    const b = d.bbox;
    const x1 = offX + b.x1 * scale, y1 = offY + b.y1 * scale;
    const x2 = offX + b.x2 * scale, y2 = offY + b.y2 * scale;
    const w = x2 - x1, h = y2 - y1;
    if (w <= 0 || h <= 0) continue;
    const c = colors[d.label] || colors.unknown;
    ctx.save();
    ctx.shadowColor = c; ctx.shadowBlur = 6;
    ctx.strokeStyle = c; ctx.lineWidth = 2;
    ctx.strokeRect(x1, y1, w, h);
    ctx.restore();
    const lbl = OBJ_LABEL[d.label] || d.label || '';
    if (lbl){
      const padX = 6, pillH = 18;
      const tw = ctx.measureText(lbl).width;
      const pillY = Math.max(0, y1 - pillH - 2);
      ctx.fillStyle = 'rgba(0,0,0,0.72)';
      ctx.fillRect(x1, pillY, tw + padX * 2, pillH);
      ctx.fillStyle = c;
      ctx.fillText(lbl, x1 + padX, pillY + 3);
    }
  }
}

// One-time wiring for the load/resize repaint triggers. The IIFE runs
// on import; null-guards make it safe against templates that omit
// the lightbox shell (e.g. wizard-only views).
(function _initLbDetectionsHooks(){
  const imgEl = byId('lightboxImg');
  const videoEl = byId('lightboxVideo');
  if (imgEl) imgEl.addEventListener('load', () => _lbDrawDetections());
  if (videoEl) videoEl.addEventListener('loadedmetadata', () => _lbDrawDetections());
  let _raf = 0;
  window.addEventListener('resize', () => {
    if (!byId('lightboxModal') || byId('lightboxModal').classList.contains('hidden')) return;
    cancelAnimationFrame(_raf);
    _raf = requestAnimationFrame(_lbDrawDetections);
  });
})();
