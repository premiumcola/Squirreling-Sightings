// ─── camedit/camera_id.js ──────────────────────────────────────────────────
// Stage 7 of the legacy.js → ES modules refactor — the JS port of
// `app/app/camera_id.py`. Must stay bit-for-bit identical to the
// Python implementation; the backend treats the persisted id as
// authoritative, this preview just shows the user what
// build_camera_id() will compute on save so there are no surprises
// when storage_migration kicks in.
//
// Schema: manufacturer_model_name_iplastoctet (each segment lowercased,
// alphanumeric-only after NFKD-strip, with German + Spanish/Portuguese
// fold-tables applied first).
import { byId } from '../core/dom.js';

const _CAM_ID_TRANSLIT = {
  'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'Ä': 'ae', 'Ö': 'oe', 'Ü': 'ue',
  'ß': 'ss', 'ñ': 'n', 'ç': 'c',
};

function _camIdSanitise(seg){
  if (seg == null) return '';
  let s = String(seg).replace(/./g, ch => _CAM_ID_TRANSLIT[ch] ?? ch);
  // NFKD decompose, drop combining marks (mirrors python unicodedata)
  s = s.normalize('NFKD').replace(/[̀-ͯ]/g, '');
  s = s.toLowerCase().replace(/[^a-z0-9]+/g, '');
  return s;
}

function _camIdLastIpSegment(ip){
  if (!ip) return '';
  const s = String(ip).trim();
  if (s.indexOf('.') >= 0){
    const last = s.split('.').pop();
    const san = _camIdSanitise(last);
    if (san) return san;
  }
  if (s.indexOf(':') >= 0){
    const noZone = s.split('%')[0];
    const last = noZone.split(':').pop();
    const san = _camIdSanitise(last);
    if (san) return san;
  }
  return '';
}

export function buildCameraId(manufacturer, model, name, ip){
  const parts = [manufacturer, model, name].map(raw => {
    const c = _camIdSanitise(raw);
    return c || 'unknown';
  });
  const ipSeg = _camIdLastIpSegment(ip);
  parts.push(ipSeg || 'unknown');
  return parts.join('_');
}

export function _refreshCamIdPreview(){
  const el = byId('camIdPreview');
  if (!el) return;
  const f = byId('cameraForm')?.elements;
  if (!f) return;
  const newId = buildCameraId(
    f['manufacturer']?.value || '',
    f['model']?.value || '',
    f['name']?.value || '',
    f['rtsp_ip']?.value || '',
  );
  el.textContent = newId;
}

export function _bindCamIdPreviewListeners(){
  const form = byId('cameraForm');
  if (!form || form.dataset.idPreviewWired) return;
  ['manufacturer', 'model', 'name', 'rtsp_ip'].forEach(n => {
    const el = form.elements[n];
    if (el) el.addEventListener('input', _refreshCamIdPreview);
  });
  form.dataset.idPreviewWired = '1';
}
