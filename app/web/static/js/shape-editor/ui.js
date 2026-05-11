// ─── shape-editor/ui.js ────────────────────────────────────────────────────
// Drawing-bar + mode buttons + polygon-list rendering. All the auxiliary
// UI bits around the canvas; reads polygon shape via geometry helpers
// and persists changes via persistence.saveShapesIntoForm. Inline-onclick
// bridges live at the bottom because the rendered HTML uses
// onclick="window.X(...)" by name; those names must be reachable from
// the global scope at template-execution time.
import { byId, esc } from '../core/dom.js';
import { shapeState } from '../core/state.js';
import { _polyPoints, _polyLabel, _polyLabels } from './geometry.js';
import { drawShapes, _SHAPE_LABEL_OPTS } from './canvas.js';
import { saveShapesIntoForm } from './persistence.js';


export function _updateShapeDrawingBar(){
  const bar = byId('shapeDrawingBar');
  if (!bar) return;
  const n = shapeState.points.length;
  bar.hidden = n === 0;
  const count = byId('shapeDrawingCount');
  if (count){
    // Prefix the current mode so the user always knows what they're
    // about to commit — drawing in zone mode reads "Zone · 3 Punkte
    // gesetzt …", drawing in mask mode reads "Maske · 3 Punkte …".
    const modeLbl = shapeState.mode === 'mask' ? 'Maske' : 'Zone';
    const tail = n < 3
      ? `${n} Punkt${n === 1 ? '' : 'e'} gesetzt · Mindestens 3 für ein Polygon`
      : `${n} Punkte gesetzt · Übernehmen möglich`;
    count.textContent = `${modeLbl} · ${tail}`;
  }
  const save = byId('saveShapeBtn');
  if (save) save.disabled = n < 3;
}

// Tracks which row's trigger options panel is currently expanded.
// Keyed as `${kind}:${idx}`. Auto-expands the row that gets selected
// via canvas click (see onUp in pointer.js).
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


// Inline onclick="..." callsites on shape rows / chips — these names are
// rendered into innerHTML strings above and need to be reachable from
// the global scope when the template fires.
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
