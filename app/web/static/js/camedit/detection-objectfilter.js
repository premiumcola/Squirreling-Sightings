// ─── camedit/detection-objectfilter.js ─────────────────────────────────────
// Per-camera object-filter pills (Person/Cat/Bird/Car/Dog/Squirrel) inside
// the Erkennung tab. Same visual recipe as the Mediathek filter bar —
// active pill fills with the object colour via --cb. _camObjectFilterState
// mirrors the hidden #object_filter input so the existing save flow
// doesn't change.
import { byId } from '../core/dom.js';
import { objIconSvg } from '../core/icons.js';
import { classColor } from '../core/class-colors.js';

// German `label` field stays local (locale, not colour) but the `cb`
// hex now pulls from class-colors.js so a palette change in one place
// propagates everywhere.
const _CAM_OBJ_OPTIONS = [
  { k: 'person',   label: 'Person',       cb: classColor('person') },
  { k: 'cat',      label: 'Katze',        cb: classColor('cat') },
  { k: 'bird',     label: 'Vogel',        cb: classColor('bird') },
  { k: 'car',      label: 'Auto',         cb: classColor('car') },
  { k: 'dog',      label: 'Hund',         cb: classColor('dog') },
  { k: 'squirrel', label: 'Eichhörnchen', cb: classColor('squirrel') },
];

let _camObjectFilterState = [];

export function getCamObjectFilterState(){ return _camObjectFilterState.slice(); }
export function setCamObjectFilterState(arr){
  _camObjectFilterState = [...(arr || [])];
}

export function _renderCamObjectPills(){
  const host = byId('camObjectFilter');
  if (!host) return;
  const active = new Set(_camObjectFilterState);
  host.innerHTML = _CAM_OBJ_OPTIONS.map(o => {
    const on = active.has(o.k);
    return `<button type="button" class="cam-obj-pill${on ? ' active' : ''}" data-obj="${o.k}" style="--cb:${o.cb}"><span class="cop-ico">${objIconSvg(o.k, 16) || ''}</span><span>${o.label}</span></button>`;
  }).join('');
  host.querySelectorAll('.cam-obj-pill').forEach(btn => {
    btn.addEventListener('click', () => {
      const k = btn.dataset.obj;
      if (active.has(k)){ active.delete(k); btn.classList.remove('active'); }
      else { active.add(k); btn.classList.add('active'); }
      _camObjectFilterState = [..._CAM_OBJ_OPTIONS.map(o => o.k).filter(x => active.has(x))];
      const hidden = byId('cameraForm').elements['object_filter'];
      if (hidden) hidden.value = _camObjectFilterState.join(',');
    });
  });
}
