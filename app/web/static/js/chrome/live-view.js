// ─── chrome/live-view.js ───────────────────────────────────────────────────
// Per-camera live-view modal. Default path uses a native <video>
// element fed HLS (hls.js on Chrome / Firefox / Edge, native on
// Safari + iOS) so the browser's built-in controls give the user
// Play / Pause / Volume / Picture-in-Picture / true iOS fullscreen
// for free. The legacy <img>+MJPEG path stays alongside as a
// fallback for the rare browser that can't do HLS at all (and for
// cameras where the per-cam streaming.hls_enabled is false).
//
// HD/SD toggle is irrelevant once HLS is engaged (one stream per
// camera) — the HD button hides itself in that mode and only
// surfaces when the MJPEG fallback drives the modal.
import { byId } from '../core/dom.js';
import { _hdCards } from '../dashboard.js';

let _liveViewCamId = null;
let _hlsInstance = null;
let _liveViewUsingHls = false;

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
  _attachLiveStream();
  const imgEl = byId('liveViewImg');
  // Image click is intentionally NOT a fullscreen toggle — only the
  // FS button on the modal owns that. (HLS path uses the native
  // <video> controls' own fullscreen icon, which is the YouTube-
  // style native player on iPhone.)
  if (imgEl) imgEl.onclick = null;
  modal.classList.remove('hidden');
  document.body.style.overflow = 'hidden';
}

// Internal — wire either HLS (preferred) or MJPEG into the modal's
// two media elements. Tears down any previous HLS instance first
// so re-opening the modal on a different camera doesn't leak the
// old session.
function _attachLiveStream(){
  if (!_liveViewCamId) return;
  const video = byId('liveViewVideo');
  const img = byId('liveViewImg');
  const hdBtn = byId('liveViewHdBtn');
  _teardownHls();
  if (video){ video.pause(); video.removeAttribute('src'); video.load?.(); }
  if (img) img.src = '';
  const hlsUrl = `/api/camera/${encodeURIComponent(_liveViewCamId)}/live.m3u8`;
  const Hls = window.Hls;
  // Path 1 — hls.js (Chrome / Firefox / Edge / Chromium on desktop).
  if (video && Hls && typeof Hls.isSupported === 'function' && Hls.isSupported()){
    try {
      _hlsInstance = new Hls({ lowLatencyMode: true });
      _hlsInstance.loadSource(hlsUrl);
      _hlsInstance.attachMedia(video);
      _hlsInstance.on(Hls.Events.ERROR, (_evt, data) => {
        // Fatal error → fall back to MJPEG. Non-fatal errors are
        // recoverable; hls.js handles them internally.
        if (data && data.fatal){
          _teardownHls();
          _attachMjpegFallback();
        }
      });
      video.style.display = 'block';
      if (img) img.style.display = 'none';
      _liveViewUsingHls = true;
      if (hdBtn) hdBtn.style.display = 'none';
      return;
    } catch { _teardownHls(); }
  }
  // Path 2 — Safari / iOS native HLS (no hls.js needed). canPlayType
  // returns 'maybe' or 'probably' when supported.
  if (video && video.canPlayType('application/vnd.apple.mpegurl')){
    video.src = hlsUrl;
    video.style.display = 'block';
    if (img) img.style.display = 'none';
    _liveViewUsingHls = true;
    if (hdBtn) hdBtn.style.display = 'none';
    return;
  }
  // Path 3 — MJPEG fallback. Shows the HD toggle so the user retains
  // the legacy SD ↔ HD switch.
  _attachMjpegFallback();
}

function _attachMjpegFallback(){
  _liveViewUsingHls = false;
  const video = byId('liveViewVideo');
  const img = byId('liveViewImg');
  const hdBtn = byId('liveViewHdBtn');
  if (video){ video.style.display = 'none'; }
  if (img){ img.style.display = 'block'; }
  if (hdBtn) hdBtn.style.display = '';
  _setLiveViewStream(window._liveViewHd);
}

function _teardownHls(){
  if (_hlsInstance){
    try { _hlsInstance.destroy(); } catch { /* ignore */ }
    _hlsInstance = null;
  }
  _liveViewUsingHls = false;
}

export function _setLiveViewStream(hd){
  // MJPEG-fallback HD/SD switch. No-op when HLS owns the modal —
  // the HD button is hidden in that case, but a stray external
  // window._setLiveViewStream call still shouldn't bleed past the
  // fallback path.
  window._liveViewHd = hd;
  if (_liveViewUsingHls) return;
  const img = byId('liveViewImg');
  if (!img || !_liveViewCamId) return;
  img.src = ''; // disconnect current stream first
  const url = hd ? `/api/camera/${encodeURIComponent(_liveViewCamId)}/stream_hd.mjpg`
                 : `/api/camera/${encodeURIComponent(_liveViewCamId)}/stream.mjpg`;
  img.src = url;
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
  _teardownHls();
  const video = byId('liveViewVideo');
  if (video){
    video.pause();
    video.removeAttribute('src');
    video.load?.();
  }
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
