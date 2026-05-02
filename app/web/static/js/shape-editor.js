// ─── shape-editor.js ───────────────────────────────────────────────────────
// Stage 9 of the legacy.js → ES modules refactor — the polygon zone /
// mask editor on the cam-edit "Erkennung" tab. Renders a snapshot
// onto a canvas, lets the user draw zones (event triggers) and masks
// (motion-suppress regions) by clicking points. Owns:
//   • Canvas drawing primitives (drawPoly, drawShapes, scaleForCanvas)
//   • Snapshot loading (loadMaskSnapshot, _maskCanvasFallback)
//   • Drawing-state UI (drawing-bar, mode buttons, polygon list)
//   • Per-polygon trigger-flags + label-scope chips
//   • Canvas mouse + touch wiring (drag vertex, click points, close)
//   • Toolbar buttons (mode switch, undo, save, clear, refresh-snapshot)
//
// shapeState lives in core/state.js — every read/write goes through
// the imported singleton so the editor + the surrounding cam-edit
// flow share one source of truth.
import { byId, esc } from './core/dom.js';
import { shapeState } from './core/state.js';
import { showToast, showConfirm } from './core/toast.js';

export function getCanvasCtx(){ return byId('maskCanvas').getContext('2d'); }

// If the snapshot fails (camera offline, no recent frame, etc.) we
// still want a usable drawing surface — set the canvas to a fixed
// 1280×720 gray placeholder so clicks are mapped to a real coordinate
// space and the user can draw zones blind.
function _maskCanvasFallback(){
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

export function loadMaskSnapshot(camId){
  if (!camId) return;
  const img = byId('maskSnapshot');
  if (!img) return;
  // Wire one-shot handlers so a failed load still leaves us with a
  // usable canvas instead of a 0×0 surface that swallows clicks.
  img.onload = () => {
    // A real snapshot is back — drop any aspect-ratio lock left
    // behind by a previous fallback render so the wrap follows the
    // image again.
    const wrap = byId('maskCanvas')?.parentElement;
    if (wrap) wrap.style.aspectRatio = '';
    drawShapes();
  };
  img.onerror = () => { _maskCanvasFallback(); drawShapes(); };
  img.src = `/api/camera/${camId}/snapshot.jpg?t=${Date.now()}`;
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

// Polygon shape: {points:[{x,y},...], label:"Zone 1"}. Raw arrays of
// points (legacy pre-label format) are still accepted — _polyPoints
// unwraps both shapes transparently.
function _polyPoints(p){ return Array.isArray(p) ? p : (p?.points || []); }
function _polyLabel(p, fallback){ return (p && p.label) || fallback; }
function _polyLabels(p){
  if (!p || typeof p !== 'object') return [];
  return Array.isArray(p.labels) ? p.labels.slice() : [];
}

function _nextPolyName(kind){
  const list = kind === 'zone' ? (shapeState.zones || []) : (shapeState.masks || []);
  const base = kind === 'zone' ? 'Zone' : 'Maske';
  const used = new Set();
  for (const p of list){
    const lbl = (p && p.label) || '';
    const m = lbl.match(new RegExp('^' + base + '\\s+(\\d+)$', 'i'));
    if (m) used.add(parseInt(m[1], 10));
  }
  let n = 1;
  while (used.has(n)) n++;
  return `${base} ${n}`;
}

// Labels available for per-polygon scoping. Mirrors KNOWN_OBJECT_LABELS
// in schema.py — keep in sync if a new class joins the detector.
const _SHAPE_LABEL_OPTS = [
  { k: 'person',   l: 'Person' },
  { k: 'cat',      l: 'Katze' },
  { k: 'bird',     l: 'Vogel' },
  { k: 'car',      l: 'Auto' },
  { k: 'dog',      l: 'Hund' },
  { k: 'squirrel', l: 'Eichhörnchen' },
];

function drawPoly(ctx, poly, color, fillAlpha, emphasised, kind, idx){
  const pts = _polyPoints(poly);
  if (!pts.length) return;
  ctx.beginPath();
  ctx.moveTo(pts[0].x, pts[0].y);
  pts.slice(1).forEach(p => ctx.lineTo(p.x, p.y));
  ctx.closePath();
  ctx.fillStyle = color.replace('1)', `${fillAlpha})`);
  ctx.strokeStyle = color;
  ctx.lineWidth = emphasised ? 5 : 3;
  ctx.fill();
  ctx.stroke();
  // Vertex handles — filled circles in the polygon colour with a white
  // border. The currently-hovered vertex gets a larger radius so the
  // user sees what they're about to grab. The DRAW position is clamped
  // to keep the full circle inside the canvas; the underlying coordinate
  // is left alone, so hit-testing still uses the real point.
  const hov = shapeState.hoverVertex;
  const isHov = (j) => hov && hov.kind === kind && hov.polyIdx === idx && hov.ptIdx === j;
  const cw = ctx.canvas.width, chh = ctx.canvas.height;
  for (let j = 0; j < pts.length; j++){
    const r = isHov(j) ? 13 : 10;
    const dx = Math.max(r, Math.min(cw - r, pts[j].x));
    const dy = Math.max(r, Math.min(chh - r, pts[j].y));
    ctx.beginPath();
    ctx.arc(dx, dy, r, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 2;
    ctx.stroke();
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
  (shapeState.zones || []).forEach((p, i) => drawPoly(ctx, p, 'rgba(75,163,255,1)', 0.17, pulseId === `zone:${i}`, 'zone', i));
  (shapeState.masks || []).forEach((p, i) => drawPoly(ctx, p, 'rgba(255,107,107,1)', 0.18, pulseId === `mask:${i}`, 'mask', i));
  if (shapeState.points.length){
    ctx.beginPath();
    ctx.moveTo(shapeState.points[0].x, shapeState.points[0].y);
    shapeState.points.slice(1).forEach(p => ctx.lineTo(p.x, p.y));
    ctx.strokeStyle = '#ffffff';
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
    const cw = canvas.width, chh = canvas.height;
    const clamp = (v, r, max) => Math.max(r, Math.min(max - r, v));
    shapeState.points.forEach((p) => {
      const r = 10;
      const dx = clamp(p.x, r, cw);
      const dy = clamp(p.y, r, chh);
      ctx.beginPath();
      ctx.arc(dx, dy, r, 0, Math.PI * 2);
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

function canvasPoint(evt){
  const canvas = byId('maskCanvas');
  const rect = canvas.getBoundingClientRect();
  // Support both mouse and touch events. Touch coords live on .touches
  // (move/start) or .changedTouches (end).
  const src = (evt.touches && evt.touches[0]) || (evt.changedTouches && evt.changedTouches[0]) || evt;
  const x = (src.clientX - rect.left) * (canvas.width / rect.width);
  const y = (src.clientY - rect.top) * (canvas.height / rect.height);
  return { x: Math.round(x), y: Math.round(y) };
}

export function saveShapesIntoForm(){
  const f = byId('cameraForm').elements;
  f['zones_json'].value = JSON.stringify(shapeState.zones || []);
  f['masks_json'].value = JSON.stringify(shapeState.masks || []);
}

// ── Shape-editor UI updaters ─────────────────────────────────────────────
export function _updateShapeDrawingBar(){
  const bar = byId('shapeDrawingBar');
  if (!bar) return;
  const n = shapeState.points.length;
  bar.hidden = n === 0;
  const count = byId('shapeDrawingCount');
  if (count){
    if (n < 3) count.textContent = `${n} Punkt${n === 1 ? '' : 'e'} gesetzt · Mindestens 3 für ein Polygon`;
    else count.textContent = `${n} Punkte gesetzt · Übernehmen möglich`;
  }
  const save = byId('saveShapeBtn');
  if (save) save.disabled = n < 3;
}

export function _updateShapeModeButtons(){
  document.querySelectorAll('.shape-mode-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.mode === shapeState.mode);
  });
}

// Tracks which row's trigger options panel is currently expanded.
// Keyed as `${kind}:${idx}`. Auto-expands the row that gets selected
// via canvas click (see onUp in the editor).
shapeState.expandedRows = shapeState.expandedRows || new Set();

export function _renderShapeList(){
  const host = byId('shapeList');
  if (!host) return;
  const zones = shapeState.zones || [];
  const masks = shapeState.masks || [];
  const clearRow = byId('shapeClearRow');
  if (clearRow) clearRow.hidden = (zones.length + masks.length) === 0;
  if (zones.length + masks.length === 0){
    host.innerHTML = '<div class="field-help" style="padding:8px 2px">Noch keine Polygone. Wähle oben einen Modus und klicke Punkte auf den Snapshot.</div>';
    return;
  }
  const row = (p, i, kind) => {
    const pts = _polyPoints(p);
    const label = _polyLabel(p, kind === 'zone' ? `Zone ${i + 1}` : `Maske ${i + 1}`);
    const pulseKey = `${kind}:${i}`;
    const polyLabels = new Set(_polyLabels(p));
    const allOn = polyLabels.size === 0;
    const expanded = shapeState.expandedRows.has(pulseKey);
    const checks = `<label class="shape-lbl-chip${allOn ? ' shape-lbl-chip--on' : ''}"><input type="checkbox" ${allOn ? 'checked' : ''} onclick="event.stopPropagation();_setShapeAllLabels('${kind}',${i},this.checked)"><span>Alle</span></label>`
      + _SHAPE_LABEL_OPTS.map(o => {
        const on = polyLabels.has(o.k);
        return `<label class="shape-lbl-chip${on ? ' shape-lbl-chip--on' : ''}"><input type="checkbox" ${on ? 'checked' : ''} onclick="event.stopPropagation();_toggleShapeLabel('${kind}',${i},'${o.k}',this.checked)"><span>${o.l}</span></label>`;
      }).join('');
    // Trigger flags are zone-only: masks just exclude motion/detection so
    // there's nothing to trigger from. The chevron button is suppressed
    // for masks; the whole trigger panel block stays out of their markup.
    let triggerHtml = '';
    if (kind === 'zone'){
      const sp = p?.save_photo !== false;
      const sv = p?.save_video !== false;
      const st = p?.send_telegram !== false;
      triggerHtml = `<div class="shape-trig-row${expanded ? ' shape-trig-row--open' : ''}">
        <label class="shape-trig-chip${sp ? ' shape-trig-chip--on' : ''}"><input type="checkbox" ${sp ? 'checked' : ''} onclick="event.stopPropagation();_toggleShapeOption('${kind}',${i},'save_photo',this.checked)"><span>📸 Foto</span></label>
        <label class="shape-trig-chip${sv ? ' shape-trig-chip--on' : ''}"><input type="checkbox" ${sv ? 'checked' : ''} onclick="event.stopPropagation();_toggleShapeOption('${kind}',${i},'save_video',this.checked)"><span>🎥 Video</span></label>
        <label class="shape-trig-chip${st ? ' shape-trig-chip--on' : ''}"><input type="checkbox" ${st ? 'checked' : ''} onclick="event.stopPropagation();_toggleShapeOption('${kind}',${i},'send_telegram',this.checked)"><span>📨 Telegram</span></label>
      </div>`;
    }
    const chev = (kind === 'zone')
      ? `<button type="button" class="shape-row-chev${expanded ? ' shape-row-chev--open' : ''}" title="Aufnahme-Optionen" onclick="event.stopPropagation();_toggleShapeExpanded('${kind}',${i})"><svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="5,3 11,8 5,13"/></svg></button>`
      : '';
    return `<div class="shape-row${shapeState.pulse === pulseKey ? ' pulse' : ''}" data-kind="${kind}" data-idx="${i}" id="shapeRow_${kind}_${i}" onclick="_pulseShape('${kind}',${i})">
      <div class="shape-row-head">
        <span class="shape-row-dot shape-row-dot--${kind}"></span>
        <span class="shape-row-label">${esc(label)}</span>
        <span class="shape-row-count">${pts.length} Punkte</span>
        ${chev}
        <button type="button" class="shape-row-del" title="Löschen" onclick="event.stopPropagation();_deleteShape('${kind}',${i})"><svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="2,4 14,4"/><path d="M5 4V2h6v2"/><path d="M3 4l1 10h8l1-10"/></svg></button>
      </div>
      <div class="shape-lbl-row">${checks}</div>
      ${triggerHtml}
    </div>`;
  };
  host.innerHTML =
      zones.map((p, i) => row(p, i, 'zone')).join('')
    + masks.map((p, i) => row(p, i, 'mask')).join('');
}

// Inline onclick="..." callsites on shape rows / chips.
window._toggleShapeExpanded = function(kind, idx){
  const key = `${kind}:${idx}`;
  if (shapeState.expandedRows.has(key)) shapeState.expandedRows.delete(key);
  else shapeState.expandedRows.add(key);
  _renderShapeList();
};

window._toggleShapeOption = function(kind, idx, key, on){
  const arr = kind === 'zone' ? shapeState.zones : shapeState.masks;
  const poly = arr[idx];
  if (!poly) return;
  poly[key] = !!on;
  saveShapesIntoForm();
  _renderShapeList();
};

window._toggleShapeLabel = function(kind, idx, labelKey, on){
  const arr = kind === 'zone' ? shapeState.zones : shapeState.masks;
  const poly = arr[idx];
  if (!poly) return;
  const set = new Set(_polyLabels(poly));
  if (on) set.add(labelKey);
  else set.delete(labelKey);
  poly.labels = [...set];
  saveShapesIntoForm();
  drawShapes();
  _renderShapeList();
};

window._setShapeAllLabels = function(kind, idx, allOn){
  const arr = kind === 'zone' ? shapeState.zones : shapeState.masks;
  const poly = arr[idx];
  if (!poly) return;
  // "Alle" checked → empty labels list (= applies to every label,
  // legacy semantics). Unchecking it leaves the existing labels
  // untouched.
  if (allOn) poly.labels = [];
  saveShapesIntoForm();
  drawShapes();
  _renderShapeList();
};

window._pulseShape = function(kind, idx){
  shapeState.pulse = shapeState.pulse === `${kind}:${idx}` ? null : `${kind}:${idx}`;
  drawShapes();
  _renderShapeList();
};

window._deleteShape = function(kind, idx){
  const arr = kind === 'zone' ? shapeState.zones : shapeState.masks;
  arr.splice(idx, 1);
  if (shapeState.pulse === `${kind}:${idx}`) shapeState.pulse = null;
  saveShapesIntoForm();
  drawShapes();
  _renderShapeList();
};

// ── Canvas wiring (drag + touch + toolbar) ───────────────────────────────
// Hit-test radius for vertex-grab and close-polygon detection. 12px is
// generous on mouse, comfortable on touch.
const _SHAPE_HIT_PX = 12;

function _hitVertex(pt){
  const test = (arr, kind) => {
    for (let i = arr.length - 1; i >= 0; i--){
      const pts = _polyPoints(arr[i]);
      for (let j = 0; j < pts.length; j++){
        const dx = pts[j].x - pt.x, dy = pts[j].y - pt.y;
        if (dx * dx + dy * dy <= _SHAPE_HIT_PX * _SHAPE_HIT_PX) return { kind, polyIdx: i, ptIdx: j };
      }
    }
    return null;
  };
  return test(shapeState.zones || [], 'zone') || test(shapeState.masks || [], 'mask');
}

function _isClosingPoint(pt){
  if (!shapeState.points || shapeState.points.length < 3) return false;
  const first = shapeState.points[0];
  const dx = first.x - pt.x, dy = first.y - pt.y;
  return dx * dx + dy * dy <= _SHAPE_HIT_PX * _SHAPE_HIT_PX;
}

// Ray-casting point-in-polygon test against {x,y} polygon vertices.
function _pointInPoly(pt, points){
  if (!Array.isArray(points) || points.length < 3) return false;
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++){
    const xi = points[i].x, yi = points[i].y;
    const xj = points[j].x, yj = points[j].y;
    const intersect = ((yi > pt.y) !== (yj > pt.y)) &&
                      (pt.x < (xj - xi) * (pt.y - yi) / ((yj - yi) || 1e-9) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

function _findPolygonAt(pt){
  const test = (arr, kind) => {
    for (let i = arr.length - 1; i >= 0; i--){
      const pts = _polyPoints(arr[i]);
      if (_pointInPoly(pt, pts)) return { kind, idx: i };
    }
    return null;
  };
  return test(shapeState.zones || [], 'zone') || test(shapeState.masks || [], 'mask');
}

function _commitInProgressPolygon(){
  if (shapeState.points.length < 3) return false;
  const poly = { points: [...shapeState.points], label: _nextPolyName(shapeState.mode) };
  if (shapeState.mode === 'zone') shapeState.zones.push(poly);
  else shapeState.masks.push(poly);
  shapeState.points = [];
  saveShapesIntoForm();
  drawShapes();
  _updateShapeDrawingBar();
  _renderShapeList();
  showToast(`${poly.label} gespeichert`, 'success');
  return true;
}

(function _initShapeEditor(){
  const canvas = byId('maskCanvas');
  if (!canvas) return;

  let drag = null;          // {kind, polyIdx, ptIdx} while dragging a vertex
  let downPt = null;        // pointer at mousedown — distinguishes click vs drag

  const onDown = (evt) => {
    if (!shapeState.camera) return;
    if (evt.cancelable) evt.preventDefault();
    const pt = canvasPoint(evt);
    const hit = _hitVertex(pt);
    if (hit){
      drag = hit;
      downPt = pt;
      return;
    }
    // No vertex grabbed → record the down position so the corresponding
    // up-event knows whether the user actually clicked or just brushed
    // the canvas. New points are added on up (with no movement) so a
    // missed drag-attempt doesn't accidentally drop a stray vertex.
    downPt = pt;
    drag = null;
  };

  const onMove = (evt) => {
    if (!shapeState.camera) return;
    const pt = canvasPoint(evt);
    if (drag){
      if (evt.cancelable) evt.preventDefault();
      const arr = drag.kind === 'zone' ? shapeState.zones : shapeState.masks;
      const poly = arr[drag.polyIdx];
      const pts = _polyPoints(poly);
      if (!pts || !pts[drag.ptIdx]) return;
      pts[drag.ptIdx].x = Math.round(pt.x);
      pts[drag.ptIdx].y = Math.round(pt.y);
      drawShapes();
      return;
    }
    // Plain hover: track which vertex (if any) is under the cursor so
    // drawShapes can highlight it and the canvas cursor updates.
    const hover = _hitVertex(pt);
    const closing = !hover && _isClosingPoint(pt);
    const sig = hover ? `${hover.kind}:${hover.polyIdx}:${hover.ptIdx}` : (closing ? 'close' : '');
    if (sig !== shapeState.hoverSig){
      shapeState.hoverVertex = hover;
      shapeState.hoverClosing = closing;
      shapeState.hoverSig = sig;
      canvas.style.cursor = (hover ? 'move' : (closing ? 'pointer' : 'crosshair'));
      drawShapes();
    }
  };

  const onUp = (evt) => {
    if (!shapeState.camera){ drag = null; downPt = null; return; }
    if (drag){
      saveShapesIntoForm();
      drag = null;
      downPt = null;
      return;
    }
    if (!downPt) return;
    const pt = canvasPoint(evt);
    // Treat as a click only when the pointer didn't move significantly.
    const dx = pt.x - downPt.x, dy = pt.y - downPt.y;
    downPt = null;
    if (dx * dx + dy * dy > 9) return;  // moved more than 3 px → ignore
    if (evt.cancelable) evt.preventDefault();
    if (_isClosingPoint(pt)){
      _commitInProgressPolygon();
      shapeState.hoverClosing = false;
      canvas.style.cursor = 'crosshair';
      return;
    }
    // While not drawing, a click on an existing polygon SELECTS it; a
    // click in empty canvas DESELECTS (if anything was selected). New
    // points are only added when nothing was selected and the click
    // missed every polygon — that preserves the legacy "click empty
    // area to draw" UX.
    if (shapeState.points.length === 0){
      const hit = _findPolygonAt(pt);
      if (hit){
        const key = `${hit.kind}:${hit.idx}`;
        shapeState.pulse = key;
        shapeState.expandedRows.add(key);
        drawShapes();
        _renderShapeList();
        const row = byId(`shapeRow_${hit.kind}_${hit.idx}`);
        if (row && row.scrollIntoView) row.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        return;
      }
      if (shapeState.pulse){
        shapeState.pulse = null;
        drawShapes();
        _renderShapeList();
        return;
      }
    }
    shapeState.points.push(pt);
    drawShapes();
    _updateShapeDrawingBar();
  };

  canvas.addEventListener('mousedown', onDown);
  canvas.addEventListener('mousemove', onMove);
  canvas.addEventListener('mouseup',   onUp);
  canvas.addEventListener('mouseleave', () => {
    drag = null;
    downPt = null;
    shapeState.hoverVertex = null;
    shapeState.hoverClosing = false;
    shapeState.hoverSig = '';
    canvas.style.cursor = 'crosshair';
    drawShapes();
  });
  canvas.addEventListener('touchstart', onDown, { passive: false });
  canvas.addEventListener('touchmove',  onMove, { passive: false });
  canvas.addEventListener('touchend',   onUp,   { passive: false });
  canvas.addEventListener('touchcancel', () => { drag = null; downPt = null; });

  byId('refreshMaskSnapshotBtn')?.addEventListener('click', () =>
    loadMaskSnapshot(shapeState.camera || byId('cameraForm').elements['id'].value));

  byId('editZoneBtn')?.addEventListener('click', () => {
    shapeState.mode = 'zone';
    _updateShapeModeButtons();
  });
  byId('editMaskBtn')?.addEventListener('click', () => {
    shapeState.mode = 'mask';
    _updateShapeModeButtons();
  });

  byId('undoShapeBtn')?.addEventListener('click', () => {
    shapeState.points.pop();
    drawShapes();
    _updateShapeDrawingBar();
  });

  byId('saveShapeBtn')?.addEventListener('click', () => {
    if (shapeState.points.length < 3){
      showToast('Mindestens 3 Punkte.', 'warn');
      return;
    }
    _commitInProgressPolygon();
  });

  byId('clearShapesBtn')?.addEventListener('click', async () => {
    if (!await showConfirm('Alle Zonen und Masken löschen?')) return;
    shapeState.zones = [];
    shapeState.masks = [];
    shapeState.points = [];
    shapeState.pulse = null;
    saveShapesIntoForm();
    drawShapes();
    _updateShapeDrawingBar();
    _renderShapeList();
  });

  byId('maskSnapshot')?.addEventListener('load', () => {
    drawShapes();
    _renderShapeList();
    _updateShapeModeButtons();
    _updateShapeDrawingBar();
  });
})();
