// ─── camedit/detection.js ──────────────────────────────────────────────────
// Form-field initializers + Erkennung-tab status strip + thin re-exports
// of the per-class grids, the object-filter pills, and the simulation
// sheet. R14 lifted those pieces into their own files so this surface
// stays focused on form + status concerns; existing camedit/index.js
// imports stay valid via the named re-exports at the bottom.
import { byId } from '../core/dom.js';
import { state } from '../core/state.js';

// Re-exports — preserve the existing API used by camedit/index.js so
// the consumer sees no rename. See each sub-module for the actual
// implementation.
export {
  _renderErkPerClassConfirm,
  _bindErkConfirmPerClassToggle,
  _collectConfirmationWindow,
  _renderCamConfirmGrid,
} from './detection-perclass.js';
export {
  getCamObjectFilterState,
  setCamObjectFilterState,
  _renderCamObjectPills,
} from './detection-objectfilter.js';

let _camFormInited = false;
export function _initCameraFormListeners() {
  if (_camFormInited) return;
  _camFormInited = true;
  const f = byId('cameraForm').elements;
  // Auto-generate ID from name (only for new cameras)
  f['name']?.addEventListener('input', () => {
    if (f['id'].dataset.autoGen === '1') {
      f['id'].value =
        'cam-' +
        f['name'].value
          .toLowerCase()
          .normalize('NFD')
          .replaceAll(/[̀-ͯ]/g, '')
          .replaceAll(/[^a-z0-9]+/g, '-')
          .replaceAll(/(^-|-$)/g, '');
    }
  });
}

// Erkennung-tab status strip — slim row with a coloured dot, an inline
// Coral state label, the per-frame inference latency, and the seconds-
// since-last-good-frame as a relative time. Mutates the static markup
// rather than re-rendering full HTML so the dot pulse animation isn't
// restarted on every state recompute. Called from editCamera() after
// the camera has been resolved AND every 3 s by live-update.js.
export function _renderGlobalStatusRows() {
  const host = byId('camGlobalStatus');
  if (!host) return;
  const camId = byId('cameraForm')?.elements?.['id']?.value;
  const cam = (state.cameras || []).find((x) => x.id === camId) || state.cameras?.[0];
  const proc = state.config?.processing || {};
  // Prefer the backend's explicit coral_mode (one of 'tpu' /
  // 'cpu_fallback' / 'off' — see camera_runtime.status). Fall back to
  // deriving from detection_mode + coral_available for older builds /
  // tests that don't surface coral_mode yet.
  let mode = cam?.coral_mode;
  if (!mode) {
    const coralOn = !!(proc.coral_enabled ?? cam?.detection_mode !== 'motion_only');
    const coralAvail = !!cam?.coral_available;
    if (!coralOn) mode = 'off';
    else if (cam?.detection_mode === 'coral' && coralAvail) mode = 'tpu';
    else if (cam?.detection_mode === 'cpu') mode = 'cpu_fallback';
    else mode = 'off';
  }
  const variant = mode === 'tpu' ? 'is-ok' : mode === 'cpu_fallback' ? 'is-cpu' : 'is-off';
  const text =
    mode === 'tpu' ? 'Coral läuft' : mode === 'cpu_fallback' ? 'CPU-Notfall' : 'Coral aus';
  const dot = host.querySelector('.dot');
  if (dot) {
    dot.classList.remove('is-ok', 'is-cpu', 'is-off');
    dot.classList.add(variant);
  }
  const txt = host.querySelector('#erkStatusText');
  if (txt) txt.textContent = text;
  const ms = Number(cam?.inference_avg_ms);
  const msEl = byId('erkStatusMs');
  if (msEl) {
    msEl.textContent =
      Number.isFinite(ms) && ms > 0 ? `${Math.round(ms)} ms / Frame` : '— ms / Frame';
  }
  const age = Number(cam?.frame_age_s);
  const upEl = byId('erkStatusUpdated');
  if (upEl) upEl.textContent = _fmtRelativeAgeS(age);
}

export function _fmtRelativeAgeS(s) {
  if (s == null || !Number.isFinite(s)) return '—';
  if (s < 5) return 'gerade eben';
  if (s < 60) return `vor ${Math.round(s)} s`;
  if (s < 3600) return `vor ${Math.round(s / 60)} Min.`;
  if (s < 86400) return `vor ${Math.round(s / 3600)} Std.`;
  if (s < 7 * 86400) return `vor ${Math.round(s / 86400)} Tagen`;
  return 'vor >1 Woche';
}

// Inline onclick="_scrollToCoralSettings(event)" used by the Erkennung
// status-strip "Coral-Einstellungen öffnen" hyperlink.
window._scrollToCoralSettings = function (ev) {
  ev?.preventDefault();
  document.querySelector('a[href="#settings"]')?.click();
  setTimeout(() => {
    const section = byId('set-coral');
    if (!section) return;
    if (!section.classList.contains('open') && typeof window.toggleSetSection === 'function') {
      window.toggleSetSection('set-coral');
    }
    section.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, 120);
};
