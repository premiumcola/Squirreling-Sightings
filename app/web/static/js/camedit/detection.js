// ─── camedit/detection.js ──────────────────────────────────────────────────
// Form-field initializers + thin re-exports
// of the per-class grids, the object-filter pills, and the simulation
// sheet. R14 lifted those pieces into their own files so this surface
// stays focused on form + status concerns; existing camedit/index.js
// imports stay valid via the named re-exports at the bottom.
import { byId } from '../core/dom.js';

// Re-exports — preserve the existing API used by camedit/index.js so
// the consumer sees no rename. See each sub-module for the actual
// implementation.
export { _collectConfirmationWindow } from './detection-perclass.js';
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

export function _fmtRelativeAgeS(s) {
  if (s == null || !Number.isFinite(s)) return '—';
  if (s < 5) return 'gerade eben';
  if (s < 60) return `vor ${Math.round(s)} s`;
  if (s < 3600) return `vor ${Math.round(s / 60)} Min.`;
  if (s < 86400) return `vor ${Math.round(s / 3600)} Std.`;
  if (s < 7 * 86400) return `vor ${Math.round(s / 86400)} Tagen`;
  return 'vor >1 Woche';
}
