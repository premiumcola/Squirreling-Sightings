// ─── netz/_api.js ──────────────────────────────────────────────────────────
// The eight endpoints, and nothing else. Every call resolves to a plain
// object; a failed call resolves to `{ok:false}` rather than throwing,
// because a chart that fails to load must show its empty state, not a
// blank panel.

import { apiGet, apiPatch, apiPost } from '../core/api.js';

async function _safe(fn) {
  try {
    return (await fn()) || { ok: false };
  } catch {
    return { ok: false };
  }
}

export function fetchState(camId) {
  const q = camId ? `?cam=${encodeURIComponent(camId)}` : '';
  return _safe(() => apiGet(`/api/netz/state${q}`));
}

/** Commit every staged axis in ONE call — the staging bar's
 *  "Übernehmen" is a single write, not one per vertex.
 *
 *  `confirmPersonFloor` travels with the request because the server
 *  clamps `person` on a security camera to E 35 unless it is present.
 *  Only a caller that actually showed the blocking dialog may pass
 *  true — "Rückgängig" and the archive restore never do. */
export function patchAxes(camId, axes, confirmPersonFloor = false) {
  const body = { axes };
  if (confirmPersonFloor) body.confirm_person_floor = true;
  return _safe(() => apiPatch(`/api/netz/${encodeURIComponent(camId)}/axes`, body));
}

/** Kamera-Feinschliff — the camera-wide capture/motion/tracking loop
 *  fields, saved through the same partial-update route the Simulieren
 *  debug panel already uses. Returns the server's "effective" echo so
 *  the panel can confirm what actually landed after validation/clamps. */
export function patchTuning(camId, fields) {
  return _safe(() =>
    apiPatch(`/api/cameras/${encodeURIComponent(camId)}/detection-tuning`, fields),
  );
}

export function fetchPreview(camId, label, e) {
  const q = `?label=${encodeURIComponent(label)}&e=${encodeURIComponent(e)}`;
  return _safe(() => apiGet(`/api/netz/${encodeURIComponent(camId)}/preview${q}`));
}

export function resetAxis(camId, label) {
  return _safe(() =>
    apiPost(`/api/netz/${encodeURIComponent(camId)}/reset`, label ? { label } : {}),
  );
}

export function setAuto(camId, enabled) {
  return _safe(() => apiPost(`/api/netz/${encodeURIComponent(camId)}/auto`, { enabled }));
}

export function fetchArchive({ cam, label, open, offset } = {}) {
  const p = new URLSearchParams();
  if (cam) p.set('cam', cam);
  if (label) p.set('label', label);
  if (open) p.set('open', '1');
  if (offset) p.set('offset', String(offset));
  const q = p.toString();
  return _safe(() => apiGet(`/api/netz/archive${q ? `?${q}` : ''}`));
}

export function fetchArchiveRecord(eid) {
  return _safe(() => apiGet(`/api/netz/archive/${encodeURIComponent(eid)}`));
}

export function archiveFrameUrl(eid) {
  return `/api/netz/archive/${encodeURIComponent(eid)}/frame.jpg`;
}

export function restoreNet(eid) {
  return _safe(() => apiPost(`/api/netz/archive/${encodeURIComponent(eid)}/restore`, {}));
}
