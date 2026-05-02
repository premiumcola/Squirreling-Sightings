// ─── camedit/panel.js ──────────────────────────────────────────────────────
// Stage 7 of the legacy.js → ES modules refactor — the cam-edit slide
// panel's tiny but load-bearing state (which camera is currently being
// edited?) plus the two helpers that open/close the wrapper. Other
// camedit modules (rtsp, whitelist, recovery, camera_id) import
// `panelState` to read/write the active id, since editCamera() itself
// still lives in legacy.js for now.
import { byId } from '../core/dom.js';

// Object reference (not a primitive) so importers see live mutations
// across modules. `panelState.camId` is the cross-module truth — every
// callsite that used to read/write the file-local `_currentEditCamId`
// now goes through this object.
export const panelState = { camId: null };

// Reset the slide-panel to its closed state and re-park the wrapper
// back inside #cameras (its original DOM home). Idempotent — safe to
// call when the panel is already closed.
export function _restoreEditWrapper(){
  const w = byId('cameraEditWrapper');
  if (!w) return;
  w.classList.remove('slide-open');
  document.querySelectorAll('.cam-item.editing').forEach(el => el.classList.remove('editing'));
  const sec = byId('cameras');
  if (sec && w.parentElement !== sec) sec.appendChild(w);
  panelState.camId = null;
}

// Soft-close — runs the slide-out animation, then re-parks after the
// 400 ms transition. The double null-check inside the timer absorbs
// the race where renderCameraSettings has wiped the wrapper between
// the click and the reparent.
export function _closeEditPanel(){
  if (!panelState.camId) return;
  const w = byId('cameraEditWrapper');
  w?.classList.remove('slide-open');
  document.querySelectorAll('.cam-item.editing').forEach(el => el.classList.remove('editing'));
  setTimeout(() => {
    if (!w) return;
    const sec = byId('cameras');
    if (sec) sec.appendChild(w);
  }, 400);
  panelState.camId = null;
}

// live-update.js's loadAll() calls _restoreEditWrapper() via the
// window bridge — keep it bridged here so the lookup keeps working.
window._restoreEditWrapper = _restoreEditWrapper;
