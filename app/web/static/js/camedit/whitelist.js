// ─── camedit/whitelist.js ──────────────────────────────────────────────────
// Stage 7 of the legacy.js → ES modules refactor — the whitelist-chip
// editor that lets the user pick which detection profiles count as
// "whitelisted" for a given camera. Internal state is a flat array of
// profile names; the hidden form field `whitelist_names` mirrors it
// as comma-separated text on every change.
import { byId, esc } from '../core/dom.js';

let _whitelistState = [];

export function getWhitelistState(){
  // Return a defensive copy so callers can't mutate the internal array.
  // The save flow in legacy.js still reads this to populate the camera-
  // settings POST body.
  return _whitelistState.slice();
}

export function setWhitelistState(arr){
  // editCamera() seeds the chip list from the camera's persisted
  // whitelist_names; this is the one-shot setter for that flow.
  _whitelistState = [...(arr || [])];
}

export function _renderWhitelistChips(profiles, selected){
  setWhitelistState(selected);
  const el = byId('whitelistChipsContainer');
  if (!el) return;
  if (!profiles.length){
    el.innerHTML = '<span class="small muted">Keine Profile vorhanden</span>';
    _updateWhitelistHidden();
    return;
  }
  el.innerHTML = profiles.map(p => `<span class="wl-chip ${_whitelistState.includes(p.name) ? 'selected' : ''}" onclick="toggleWlChip('${esc(p.name)}')">${esc(p.name)}</span>`).join('');
  _updateWhitelistHidden();
}

export function _updateWhitelistHidden(){
  const f = byId('cameraForm')?.elements;
  if (f && f['whitelist_names']) f['whitelist_names'].value = _whitelistState.join(',');
}

// Inline onclick="toggleWlChip(...)" callsite in the chip HTML above.
// Bridged on window because each chip's handler resolves the name via
// global lookup.
window.toggleWlChip = function(name){
  const idx = _whitelistState.indexOf(name);
  if (idx >= 0) _whitelistState.splice(idx, 1);
  else _whitelistState.push(name);
  document.querySelectorAll('.wl-chip').forEach(c => c.classList.toggle('selected', _whitelistState.includes(c.textContent)));
  _updateWhitelistHidden();
};
