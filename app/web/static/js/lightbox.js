// ─── lightbox.js ───────────────────────────────────────────────────────────
// Stage 4 of the legacy.js → ES modules refactor — pure DOM helpers
// for the media-viewer lightbox. The state singletons (_lbItem,
// _lbIndex, _lbDeletePending) and the cross-domain orchestration
// (openLightbox / closeLightbox / keydown handler / openTLPlayer)
// stay in legacy.js for now; those reach into mediathek + timelapse +
// live-view modules that haven't extracted yet. Once those follow,
// the orchestration can move here too.
//
// Everything below is stateless: each function takes whatever it
// needs as an argument. No reads from a shared _lbItem singleton.
// That's what makes the slice safe to lift before its bigger
// neighbours.
import { byId } from './core/dom.js';

// Confirm-button glyph variants. _LB_CHECK_SVG = single tick (kept,
// not yet confirmed); _LB_CHECK2_SVG = double tick (already
// confirmed). _LB_HINT and _LB_TRASH_HTML are the small caption +
// trash-icon block used by the delete button.
export const _LB_CHECK_SVG  = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="4,12 9,18 20,6"/></svg>`;
export const _LB_CHECK2_SVG = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="1,13 6,18 13,9"/><polyline points="10,13 15,18 23,6"/></svg>`;
export const _LB_HINT = '<span style="font-size:9px;line-height:1;opacity:.7;white-space:nowrap">↑ behalten</span>';
export const _LB_TRASH_HTML = '<span style="font-size:14px;line-height:1;opacity:.8">↓</span><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3,6 5,6 21,6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/></svg>';

// Paint the confirm button in its current state. Caller passes the
// boolean directly so this helper never reaches back into the
// shared _lbItem.
export function _updateLbConfirmBtn(confirmed){
  const btn = byId('lightboxConfirm');
  if (!btn) return;
  if (confirmed){
    btn.style.background = '#166534';
    btn.innerHTML = _LB_CHECK2_SVG;
    btn.title = 'Bestätigt';
  } else {
    btn.style.background = '';
    btn.innerHTML = _LB_CHECK_SVG;
    btn.title = 'Behalten (↑)';
  }
}

// Clear the bbox-overlay canvas without redrawing. Used when the
// lightbox switches between media or closes; the resize/load hooks in
// legacy.js call _lbDrawDetections again next paint if we're still
// open.
export function _lbClearDetections(){
  const cv = byId('lightboxDetections');
  if (!cv) return;
  const ctx = cv.getContext('2d');
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, cv.width, cv.height);
}

// Reset the lightbox to photo mode — pause + drop any video src,
// re-show the <img>, hide the error banner, restore the confirm
// button. Called whenever a new photo item is opened so any prior
// state (lingering video, error message) doesn't leak into the new
// view.
export function _lbResetToPhoto(){
  const videoEl = byId('lightboxVideo');
  if (videoEl) {
    videoEl.pause();
    videoEl.src = '';
    videoEl.style.display = 'none';
  }
  const imgEl = byId('lightboxImg');
  if (imgEl) imgEl.style.display = '';
  _lbClearDetections();
  const errEl = byId('lightboxErrorMsg');
  if (errEl) errEl.style.display = 'none';
  const confirmBtn = byId('lightboxConfirm');
  if (confirmBtn) confirmBtn.style.display = '';
}

// Show an error banner inside the lightbox media wrap (e.g. "Video
// nicht verfügbar", "Video wird verarbeitet…"). Hides the underlying
// img/video elements so the banner reads on a clean dark backdrop.
// Banner is created lazily on first call and reused thereafter.
export function _lbShowError(text){
  let errEl = byId('lightboxErrorMsg');
  if (!errEl) {
    errEl = document.createElement('div');
    errEl.id = 'lightboxErrorMsg';
    errEl.style.cssText = 'align-items:center;justify-content:center;width:100%;min-height:240px;max-height:80vh;color:rgba(255,255,255,.55);font-size:15px;font-weight:500;background:#080510;border-radius:18px';
    const wrap = byId('lightboxMediaWrap');
    if (wrap) wrap.appendChild(errEl);
  }
  errEl.textContent = text;
  errEl.style.display = 'flex';
  const imgEl = byId('lightboxImg');
  if (imgEl) imgEl.style.display = 'none';
  const videoEl = byId('lightboxVideo');
  if (videoEl) {
    videoEl.style.display = 'none';
    videoEl.pause();
    videoEl.src = '';
  }
}
