// ─── chrome/fullscreen.js ──────────────────────────────────────────────────
// Stage 11 of the legacy.js → ES modules refactor — generic fullscreen
// wiring used by the live-view modal and the lightbox. Tries the
// Fullscreen API first; falls back to a CSS .fake-fullscreen class on
// browsers that block it (iOS Safari) so the wrap still expands.
import { byId } from '../core/dom.js';

const _FS_EXPAND   = `<svg viewBox="0 0 24 24" width="18" height="18" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>`;
const _FS_COMPRESS = `<svg viewBox="0 0 24 24" width="18" height="18" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"><path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 0 2-2h3M3 16h3a2 2 0 0 0 2 2v3"/></svg>`;

function _fsToggle(wrapEl, targetEl){
  const fsEl = document.fullscreenElement || document.webkitFullscreenElement;
  if (fsEl){
    if (document.exitFullscreen) document.exitFullscreen().catch(() => {});
    else if (document.webkitExitFullscreen) document.webkitExitFullscreen();
  } else {
    const req = targetEl.requestFullscreen || targetEl.webkitRequestFullscreen || targetEl.mozRequestFullScreen;
    if (req) req.call(targetEl).catch(() => { wrapEl.classList.add('fake-fullscreen'); });
    else wrapEl.classList.add('fake-fullscreen');
  }
}

export function _initFsBtn(btnId, wrapEl, getTarget){
  const btn = byId(btnId);
  if (!btn || !wrapEl) return;
  btn.innerHTML = _FS_EXPAND;
  btn.addEventListener('click', e => { e.stopPropagation(); _fsToggle(wrapEl, getTarget()); });
  const update = () => {
    const fsEl = document.fullscreenElement || document.webkitFullscreenElement;
    const isFs = !!(fsEl && (fsEl === wrapEl || wrapEl.contains(fsEl)));
    btn.innerHTML = isFs ? _FS_COMPRESS : _FS_EXPAND;
    if (!fsEl) wrapEl.classList.remove('fake-fullscreen');
  };
  document.addEventListener('fullscreenchange', update);
  document.addEventListener('webkitfullscreenchange', update);
}
