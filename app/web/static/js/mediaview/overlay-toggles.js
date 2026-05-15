// ─── mediaview/overlay-toggles.js ──────────────────────────────────────────
// Shared pill bar for "which overlay layers do I want to see on the
// current video viewport". Lifted out of live-detect.js (cm-47) so
// the same five pills can mount in:
//
//   * Live view + Coral test mode — full set
//     (bboxes / trails / zones / masks).
//   * Mediathek motion-clip lightbox — full set; toggles flip the
//     existing bbox-overlay layers plus the new zone overlay.
//   * Weather / sunrise / sunset / event timelapse lightbox —
//     ['zones', 'masks'] only. Bboxes / trails have no meaning for
//     a sped-up overview with no detections, so the bar renders
//     with two pills rather than four greyed-out ones.
//
// Persistence: per-context state lives in localStorage under
// ``tamspy.overlayToggles.v1``; the caller passes a ``contextKey``
// that scopes the sub-key (e.g. ``'live'``, ``'mediathek'``,
// ``'timelapse'``). The user's choice survives reloads without
// ever touching settings.json.
//
// Tooltips are the same long-press / 300 ms-hover treatment from
// cm-45, factored into a tiny helper so we don't reinvent the
// popover state per context.

import { byId, esc } from '../core/dom.js';

const _LS_KEY = 'tamspy.overlayToggles.v1';

// Master toggle metadata — every callsite picks from this dict via
// the ``available`` list. Single source of truth for label + German
// description across contexts.
//
// C1 · defaults rebalanced: detection layers (bboxes/trails) stay ON
// because the operator opens the lightbox / sim modal explicitly TO
// see them, but surveillance layers (zones/masks) flip OFF so a
// preview frame isn't cluttered with green/red polygons every time
// the modal opens.
//
// K1 · persistence is now per-toggle. Bboxes/trails persist the
// user's preference across opens (persist:true) — flip them off
// once, they stay off. Zones/masks DO NOT persist (persist:false) —
// they always re-open at default=false regardless of how the user
// left them last time. Earlier behaviour persisted everything and
// produced the "red mask polygon every clip" annoyance the user
// flagged ("I never asked for this"). The matching localStorage
// migration further down (_pruneNonPersistedFromLS) strips any
// zones/masks values that leaked into prior sessions.
const _TOGGLES = {
  bboxes:    { label: 'Bboxes',    default: true,  persist: true,
               desc: 'Erkannte Objekte als Rahmen über dem Video einblenden' },
  trails:    { label: 'Trails',    default: true,  persist: true,
               desc: 'Bewegungspfade jeder erkannten Spur einzeichnen' },
  zones:     { label: 'Zonen',     default: false, persist: false,
               desc: 'Erkennungs-Zonen (grün) anzeigen' },
  masks:     { label: 'Masken',    default: false, persist: false,
               desc: 'Ausschluss-Masken (rot) anzeigen' },
};

// K1 · one-shot migration on module load. Walks every contextKey
// stored under tamspy.overlayToggles.v1 and drops keys whose
// _TOGGLES entry has persist:false (zones, masks). Silent — no
// console output. Defensive: catches every step so a quota /
// private-mode error path can't break module init.
(function _pruneNonPersistedFromLS(){
  try {
    const raw = localStorage.getItem(_LS_KEY);
    if (!raw) return;
    const all = JSON.parse(raw);
    if (!all || typeof all !== 'object') return;
    let touched = false;
    for (const ctx of Object.keys(all)){
      const ctxState = all[ctx];
      if (!ctxState || typeof ctxState !== 'object') continue;
      for (const id of Object.keys(ctxState)){
        if (_TOGGLES[id] && _TOGGLES[id].persist === false){
          delete ctxState[id];
          touched = true;
        }
      }
    }
    if (touched) localStorage.setItem(_LS_KEY, JSON.stringify(all));
  } catch { /* private-mode / quota — silent */ }
})();

// Tooltip popover — one element, reused across contexts. Re-uses
// the .mv-live-toggle-tip class from 30-lightbox-video.css so we
// don't duplicate the styling.
let _tipEl = null;
let _tipHoverTimer = 0;
let _tipLongPressTimer = 0;

function _ensureTip(){
  if (_tipEl) return _tipEl;
  _tipEl = document.createElement('div');
  _tipEl.className = 'mv-live-toggle-tip';
  _tipEl.setAttribute('role', 'tooltip');
  _tipEl.hidden = true;
  document.body.appendChild(_tipEl);
  return _tipEl;
}

function _showTip(target, text){
  const tip = _ensureTip();
  tip.textContent = text;
  tip.hidden = false;
  const r = target.getBoundingClientRect();
  const tipR = tip.getBoundingClientRect();
  const above = r.top - tipR.height - 10;
  const top = above >= 8 ? above : r.bottom + 10;
  const vw = window.innerWidth || document.documentElement.clientWidth;
  let left = r.left + r.width / 2 - tipR.width / 2;
  left = Math.max(8, Math.min(vw - tipR.width - 8, left));
  tip.style.top = `${Math.round(top)}px`;
  tip.style.left = `${Math.round(left)}px`;
}

function _hideTip(){
  if (_tipEl) _tipEl.hidden = true;
  clearTimeout(_tipHoverTimer);
  clearTimeout(_tipLongPressTimer);
}

// Persisted-state helpers — one entry per (contextKey, layerId).
function _loadState(contextKey){
  try {
    const raw = localStorage.getItem(_LS_KEY);
    if (!raw) return {};
    const all = JSON.parse(raw);
    return (all && all[contextKey]) || {};
  } catch { return {}; }
}

function _saveState(contextKey, state){
  // K1 · filter to persistable keys only. Non-persisted toggles
  // (zones, masks) MUST NOT leak into localStorage — otherwise the
  // migration above just gets to re-clean them on every page load.
  // The filter is the single source of truth; flipping a toggle's
  // persist flag flips its localStorage participation automatically.
  const clean = {};
  for (const id of Object.keys(state || {})){
    if (_TOGGLES[id] && _TOGGLES[id].persist){
      clean[id] = !!state[id];
    }
  }
  try {
    const raw = localStorage.getItem(_LS_KEY);
    const all = raw ? (JSON.parse(raw) || {}) : {};
    all[contextKey] = clean;
    localStorage.setItem(_LS_KEY, JSON.stringify(all));
  } catch { /* quota / private mode — silent */ }
}

/**
 * Mount the pill bar into a host element.
 *
 * @param {HTMLElement|string} host  — DOM node or element id.
 * @param {Object} opts
 * @param {Array<string>} opts.available
 *   Layer ids to render. Order is preserved in the rendered bar.
 *   Live / Mediathek pass all five; Weather / timelapse pass
 *   ``['zones', 'masks']`` so detection-only pills don't appear at
 *   all (better than five greyed-out ones).
 * @param {string} opts.contextKey
 *   Stable localStorage scope key. ``'live'``, ``'mediathek'``,
 *   ``'timelapse'``, etc.
 * @param {Function} opts.onChange
 *   ``(id, on, allStates) => void``. Fires on every toggle. The
 *   caller redraws the corresponding overlay layer.
 * @param {string} [opts.hintText]
 *   Optional muted-tail text on the right ("Esc · Klicke Bbox für
 *   Details", "Drag zum Scrubben", …). Hidden on iPhone width.
 * @returns {{ getState(): Object, setState(id, on): void,
 *            teardown(): void }}
 */
export function renderOverlayToggles(host, opts = {}){
  const el = (typeof host === 'string') ? byId(host) : host;
  if (!el) return null;
  const available = (opts.available || []).filter(id => Object.prototype.hasOwnProperty.call(_TOGGLES, id));
  if (available.length === 0){
    el.innerHTML = '';
    return { getState: () => ({}), setState: () => {}, teardown: () => {} };
  }
  const contextKey = opts.contextKey || 'default';
  const persisted = _loadState(contextKey);
  // K1 · per-toggle persistence. Persistable toggles (bboxes/trails)
  // honour the localStorage value when present; non-persistable
  // toggles (zones/masks) ALWAYS initialise to their declared
  // default regardless of any leftover localStorage entry. The
  // migration above strips those from the store on load, but this
  // belt-and-suspenders also guards against a fresh write that
  // somehow lands before the migration runs.
  const state = {};
  for (const id of available){
    const t = _TOGGLES[id];
    if (t.persist && id in persisted){
      state[id] = !!persisted[id];
    } else {
      state[id] = !!t.default;
    }
  }
  // Mark the host so multiple mounts can coexist in different parts
  // of the page (live + mediathek lightbox open simultaneously, etc.)
  el.classList.add('mv-live-toggles');
  el.innerHTML = available.map(id => {
    const t = _TOGGLES[id];
    return `<button type="button" class="mv-live-toggle" data-tog="${id}" data-desc="${esc(t.desc)}" data-on="${state[id] ? '1' : '0'}" title="${esc(t.desc)}" aria-label="${esc(t.label)}: ${esc(t.desc)}">${esc(t.label)}</button>`;
  }).join('') + (opts.hintText
    ? `<span class="mv-live-toggles-hint">${esc(opts.hintText)}</span>`
    : '');
  const fireChange = (id, on) => {
    if (typeof opts.onChange === 'function'){
      try { opts.onChange(id, on, { ...state }); } catch { /* swallow */ }
    }
  };
  const teardown = [];
  el.querySelectorAll('.mv-live-toggle').forEach(btn => {
    btn.addEventListener('click', (ev) => {
      if (btn._suppressClick){ btn._suppressClick = false; ev.preventDefault(); return; }
      const id = btn.dataset.tog;
      state[id] = !state[id];
      btn.dataset.on = state[id] ? '1' : '0';
      _saveState(contextKey, state);
      _hideTip();
      fireChange(id, state[id]);
    });
    btn.addEventListener('pointerenter', (ev) => {
      if (ev.pointerType !== 'mouse') return;
      clearTimeout(_tipHoverTimer);
      _tipHoverTimer = setTimeout(() => _showTip(btn, btn.dataset.desc || ''), 300);
    });
    btn.addEventListener('pointerleave', _hideTip);
    btn.addEventListener('touchstart', () => {
      clearTimeout(_tipLongPressTimer);
      _tipLongPressTimer = setTimeout(() => {
        btn._suppressClick = true;
        _showTip(btn, btn.dataset.desc || '');
      }, 500);
    }, { passive: true });
    btn.addEventListener('touchend', () => clearTimeout(_tipLongPressTimer));
    btn.addEventListener('touchcancel', () => clearTimeout(_tipLongPressTimer));
  });
  const outsideTouch = (ev) => {
    if (!_tipEl || _tipEl.hidden) return;
    if (ev.target.closest && ev.target.closest('.mv-live-toggle')) return;
    _hideTip();
  };
  document.addEventListener('touchstart', outsideTouch, { passive: true });
  teardown.push(() => document.removeEventListener('touchstart', outsideTouch));
  return {
    getState: () => ({ ...state }),
    setState: (id, on) => {
      if (!(id in state)) return;
      state[id] = !!on;
      const btn = el.querySelector(`.mv-live-toggle[data-tog="${id}"]`);
      if (btn) btn.dataset.on = state[id] ? '1' : '0';
      _saveState(contextKey, state);
      fireChange(id, state[id]);
    },
    teardown: () => {
      for (const fn of teardown){
        try { fn(); } catch { /* ignore */ }
      }
      el.innerHTML = '';
    },
  };
}

/**
 * Convenience entry that mounts a zones+masks-only bar for the
 * weather / timelapse lightbox path. The Mediathek motion-clip
 * lightbox would call the full ``renderOverlayToggles`` directly
 * once its overlay layers are wired through this state path —
 * pending the bbox-overlay refactor for show/hide toggles.
 */
export function mountWeatherToggleBar(item, onChange){
  const inner = byId('lightboxInner');
  const stack = byId('lightboxBottomStack');
  if (!inner || !stack) return null;
  let row = byId('mvLiveToggles');
  if (!row){
    row = document.createElement('div');
    row.id = 'mvLiveToggles';
    inner.insertBefore(row, stack);
  }
  const isTL = item?.type === 'timelapse';
  return renderOverlayToggles(row, {
    available:  isTL ? ['zones', 'masks'] : ['bboxes', 'trails', 'zones', 'masks'],
    contextKey: isTL ? 'timelapse' : 'mediathek',
    onChange,
    hintText:   'Lange drücken für Beschreibung',
  });
}

window.mountWeatherToggleBar = mountWeatherToggleBar;
