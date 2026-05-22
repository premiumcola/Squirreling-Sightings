// ─── core/action-registry.js ───────────────────────────────────────────────
// O11 · One global click/change/submit delegator. Templates wire their
// elements with ``data-action="actionName"``; this file dispatches to a
// registry of handler functions. Lets us drop inline ``onclick=`` in
// the HTML — which kept ~130 ``window.*`` bridges alive across JS
// modules just so the inline strings could resolve them.
//
// Usage:
//   import { registerAction } from './core/action-registry.js';
//   registerAction('jumpToSetting', (el, ev) => {
//     ev.preventDefault();
//     navJumpToSetting(ev, el.dataset.target);
//   });
//
// Template side:
//   <a href="#set-app" data-action="jumpToSetting" data-target="set-app">…</a>
//
// The handler receives the matched element (the closest [data-action]
// ancestor of the event target) and the original event. Returning
// `false` calls preventDefault automatically — matches the `return
// navFn(event)` idiom the inline strings used.

const _ACTIONS = new Map();

export function registerAction(name, fn) {
  if (!name || typeof fn !== 'function') return;
  _ACTIONS.set(name, fn);
}

// One delegator per event type. Mounted lazily on first registration.
// We use `closest('[data-action]')` so the trigger can be a child
// element (e.g. an SVG inside a button) without breaking the lookup.
let _wired = false;

function _handle(eventType, ev) {
  const target = ev.target?.closest?.(`[data-action]`);
  if (!target) return;
  // Filter by which event type this element listens for. The default
  // is click; data-action-event="change" / "submit" / "input" opts
  // into a different one.
  const wantedEvent = target.dataset.actionEvent || 'click';
  if (wantedEvent !== eventType) return;
  const action = target.dataset.action;
  if (!action) return;
  const fn = _ACTIONS.get(action);
  if (!fn) return;
  const result = fn(target, ev);
  if (result === false) ev.preventDefault();
}

function _wire() {
  if (_wired) return;
  _wired = true;
  document.addEventListener('click', (ev) => _handle('click', ev), { capture: false });
  document.addEventListener('change', (ev) => _handle('change', ev), { capture: false });
  document.addEventListener('submit', (ev) => _handle('submit', ev), { capture: false });
  document.addEventListener('input', (ev) => _handle('input', ev), { capture: false });
}

// Auto-wire on import so callers don't need to remember to call init.
_wire();

// ── O11 · thin shims that forward to window.* bridges ──────────────────────
// A handful of action handlers are tiny enough that defining them via
// registerAction() in their owner-module would just bloat that module
// with one-liner forwarders. Keeping them here lets the template-side
// migration land without touching every owner. As each owner migrates
// fully (`window.fn` retires), the shim here goes with it.
const _shim =
  (winName, withSecArg = null) =>
  (el) => {
    const fn = typeof window !== 'undefined' ? window[winName] : null;
    if (typeof fn !== 'function') return;
    if (withSecArg) return fn(el.dataset[withSecArg]);
    return fn();
  };
registerAction('closeLiveView', _shim('closeLiveView'));
registerAction('toggleLiveViewHd', () => {
  if (typeof window._setLiveViewStream === 'function')
    window._setLiveViewStream(!window._liveViewHd);
});
registerAction('openCamRecoveryModal', _shim('openCamRecoveryModal'));
registerAction('loadCamRecoveryDiscovery', _shim('loadCamRecoveryDiscovery'));
registerAction('closeCamRecoveryModal', _shim('closeCamRecoveryModal'));
registerAction('toggleMediaSelectMode', _shim('toggleMediaSelectMode'));
registerAction('closeMediaDrilldown', _shim('closeMediaDrilldown'));
registerAction('bulkDeleteSelectedMedia', _shim('bulkDeleteSelectedMedia'));
registerAction('toggleSetSection', _shim('toggleSetSection', 'section'));
// cam-edit Verbindung tab
registerAction('togglePwField', (el) => {
  if (typeof window.togglePwField === 'function') {
    window.togglePwField(el, el.dataset.field);
  }
});
registerAction('toggleCamRtspErw', _shim('_toggleCamRtspErw'));
registerAction('toggleUrlMask', (el) => {
  if (typeof window._toggleUrlMask === 'function') window._toggleUrlMask(el);
});
registerAction('toggleCamDiag', _shim('_toggleCamDiag'));
// settings.html
registerAction('togglePwFieldById', (el) => {
  if (typeof window.togglePwFieldById === 'function') window.togglePwFieldById(el.dataset.field);
});
registerAction('toggleCoralTab', (el) => {
  if (typeof window.toggleCoralTab === 'function') window.toggleCoralTab(el.dataset.tabTarget);
});
registerAction('toggleCoralSetting', (el) => {
  if (typeof window._toggleCoralSetting === 'function') {
    window._toggleCoralSetting(el.dataset.setting, el);
  }
});
registerAction('reloadCoralRuntime', _shim('reloadCoralRuntime'));
registerAction('saveMqttSettings', _shim('saveMqttSettings'));
// Extended toggleSetSection — supports an optional "data-also" companion
// fn for cases where opening a section triggers a side-load (Timelapse).
registerAction('toggleSetSection', (el) => {
  const sec = el.dataset.section;
  if (sec && typeof window.toggleSetSection === 'function') window.toggleSetSection(sec);
  const also = el.dataset.also;
  if (also && typeof window[also] === 'function') {
    const wrapper = el.closest('.set-section');
    if (wrapper && wrapper.classList.contains('open')) window[also]();
  }
});
