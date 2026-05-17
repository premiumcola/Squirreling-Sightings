// ─── core/hls-attach.js ────────────────────────────────────────────────────
// Shared HLS attach helper. Both `chrome/live-view.js` (per-camera Live
// modal) and `mediaview/live-detect.js` (Simulieren view) drive the
// same dual-path stream selection — hls.js on Chrome/Firefox/Edge,
// native `<video>` on Safari + iOS, MJPEG `<img>` as a last-resort
// fallback. Pulling the dual-path into one module keeps both
// consumers in lockstep when the HLS strategy evolves (e.g. low-
// latency tuning, error recovery policy).
//
// iOS Safari note: `multipart/x-mixed-replace; boundary=frame` MJPEG
// streams do NOT render in `<img>` tags on iOS — the browser shows
// a "broken image" placeholder. Every iOS-reachable view MUST go
// through HLS first; the MJPEG path is a desktop-only fallback for
// the rare browser without HLS support.

/**
 * Attach a live HLS stream to a `<video>` element. Returns a handle
 * with `kind` and `detach()` on success, or `null` when neither
 * hls.js nor native HLS is available (caller should fall back to
 * MJPEG in that case).
 *
 * @param {string} camId   — camera id (used to build the .m3u8 URL).
 * @param {HTMLVideoElement} videoEl — destination video element.
 * @param {{ onFatalError?: Function }} [opts]
 *   onFatalError — called when hls.js emits a FATAL error so the
 *   caller can swap to MJPEG fallback (live-view's behaviour).
 * @returns {{kind:string,instance:any,detach:Function}|null}
 */
export function tryAttachHls(camId, videoEl, opts = {}){
  if (!videoEl || !camId) return null;
  const hlsUrl = `/api/camera/${encodeURIComponent(camId)}/live.m3u8`;
  const Hls = window.Hls;
  // Path 1 — hls.js (Chrome / Firefox / Edge / Chromium on desktop).
  if (Hls && typeof Hls.isSupported === 'function' && Hls.isSupported()){
    try {
      const inst = new Hls({ lowLatencyMode: true });
      inst.loadSource(hlsUrl);
      inst.attachMedia(videoEl);
      if (typeof opts.onFatalError === 'function'){
        inst.on(Hls.Events.ERROR, (_evt, data) => {
          if (data && data.fatal) opts.onFatalError(data);
        });
      }
      return {
        kind: 'hls.js',
        instance: inst,
        detach: () => { try { inst.destroy(); } catch { /* ignore */ } },
      };
    } catch { /* fall through to native */ }
  }
  // Path 2 — Safari / iOS native HLS (no hls.js needed). canPlayType
  // returns 'maybe' or 'probably' when supported.
  if (videoEl.canPlayType('application/vnd.apple.mpegurl')){
    videoEl.src = hlsUrl;
    return {
      kind: 'native',
      instance: null,
      detach: () => {
        try {
          videoEl.pause();
          videoEl.removeAttribute('src');
          videoEl.load?.();
        } catch { /* ignore */ }
      },
    };
  }
  return null;
}
