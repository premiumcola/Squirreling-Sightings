// ─── chrome/live-view.js ───────────────────────────────────────────────────
// Stage 11 of the legacy.js → ES modules refactor — the per-camera
// fullscreen MJPEG modal triggered from the dashboard tile or the
// "Live öffnen" button. HD/SD toggle, fullscreen handoff, and the
// shared _hdCards state with the dashboard tile.
import { byId } from '../core/dom.js';
import { _hdCards } from '../dashboard.js';

let _liveViewCamId = null;

// _liveViewHd is exposed on window because the template reads
// `!_liveViewHd` inline in the HD-toggle button's onclick. We keep
// the bridge in lockstep with the local primitive on every set.
window._liveViewHd = false;

export function openLiveView(camId, camName){
  const modal = byId('liveViewModal');
  if (!modal) return;
  _liveViewCamId = camId;
  window._liveViewHd = _hdCards.has(camId); // inherit shared HD state
  byId('liveViewTitle').textContent = camName || camId;
  _setLiveViewStream(window._liveViewHd);
  const imgEl = byId('liveViewImg');
  // Image click no longer toggles fullscreen — the dedicated FS button owns that.
  // True iOS-native fullscreen (the YouTube experience the user referenced)
  // requires a <video> element fed by HLS or DASH. Our streams are MJPEG via
  // <img>, which iOS Safari refuses to fullscreen. requestFullscreen on the
  // wrap div does work on desktop and Chrome/Firefox-iOS; on Safari iPhone
  // it falls back to .fake-fullscreen CSS so the modal still covers the
  // chrome. A future HLS pipeline (server-side transmux of RTSP→HLS) is
  // the only path to real native fullscreen on iPhone Safari.
  if (imgEl) imgEl.onclick = null;
  modal.classList.remove('hidden');
  document.body.style.overflow = 'hidden';
}

export function _setLiveViewStream(hd){
  window._liveViewHd = hd;
  const img = byId('liveViewImg');
  if (!img || !_liveViewCamId) return;
  img.src = ''; // disconnect current stream first
  const url = hd ? `/api/camera/${encodeURIComponent(_liveViewCamId)}/stream_hd.mjpg`
                 : `/api/camera/${encodeURIComponent(_liveViewCamId)}/stream.mjpg`;
  img.src = url;
  // Shared state: keep the card's HD badge + img in sync.
  if (hd) _hdCards.add(_liveViewCamId);
  else _hdCards.delete(_liveViewCamId);
  const cardBadge = document.querySelector(`.cv-card[data-camid="${CSS.escape(_liveViewCamId)}"] .cv-hd-badge`);
  if (cardBadge) cardBadge.classList.toggle('active', hd);
  const cardImg = document.querySelector(`.cv-card[data-camid="${CSS.escape(_liveViewCamId)}"] .cv-img`);
  if (cardImg){
    if (hd && cardImg.dataset.hdMode !== '1'){
      cardImg.dataset.hdMode = '1';
      cardImg.src = `/api/camera/${encodeURIComponent(_liveViewCamId)}/stream_hd.mjpg`;
    } else if (!hd && cardImg.dataset.hdMode === '1'){
      cardImg.dataset.hdMode = '0';
      cardImg.src = `/api/camera/${encodeURIComponent(_liveViewCamId)}/snapshot.jpg?t=${Date.now()}`;
    }
  }
  const hdBtn = byId('liveViewHdBtn');
  if (hdBtn){
    hdBtn.textContent = 'HD';
    hdBtn.style.border = 'none';
    if (hd){
      hdBtn.style.background = 'rgba(255,255,255,0.85)';
      hdBtn.style.color = '#0a0e1a';
      hdBtn.style.fontWeight = '800';
    } else {
      hdBtn.style.background = 'rgba(255,255,255,0.08)';
      hdBtn.style.color = 'rgba(255,255,255,0.35)';
      hdBtn.style.fontWeight = '700';
    }
  }
}

export function closeLiveView(){
  const modal = byId('liveViewModal');
  if (!modal) return;
  const img = byId('liveViewImg');
  if (img) img.src = ''; // disconnect MJPEG stream → remove_viewer
  if (document.fullscreenElement || document.webkitFullscreenElement){
    (document.exitFullscreen || document.webkitExitFullscreen || function(){}).call(document).catch(() => {});
  }
  const wrap = byId('liveViewWrap');
  if (wrap) wrap.classList.remove('fake-fullscreen');
  modal.classList.add('hidden');
  document.body.style.overflow = '';
  _liveViewCamId = null;
}

// Inline onclick callsites in the static template + the dashboard.js
// tile click handler reach these via window.X.
window.openLiveView = openLiveView;
window.closeLiveView = closeLiveView;
window._setLiveViewStream = _setLiveViewStream;
