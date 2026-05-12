// ─── mediaview/canvas/zone-overlay-mount.js ────────────────────────────────
// Wire the shared renderZoneLayer into the lightbox / timelapse
// playback viewport. Mounts a canvas overlay on top of the video
// element, watches the video for size + metadata changes via
// ResizeObserver + loadedmetadata, and redraws.
//
// Live view + coral test mode use their own SVG overlays via
// live-detect.js — those don't need this helper because they
// already redraw on every test-detection tick. This module is for
// passive video playback contexts where there is no per-frame
// callback.

import { state } from '../../core/state.js';
import { renderZoneLayerForMediaEl } from './zone-layer.js';

const _ZONE_CANVAS_ID = 'lightboxZoneOverlay';
let _resizeObs = null;
let _videoEl = null;
let _onMeta = null;
let _onResize = null;

function _ensureCanvas(wrap){
  let c = document.getElementById(_ZONE_CANVAS_ID);
  if (c) return c;
  c = document.createElement('canvas');
  c.id = _ZONE_CANVAS_ID;
  c.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:4';
  wrap.appendChild(c);
  return c;
}

/**
 * Mount the zone overlay on the lightbox video. ``item`` provides
 * the camera id (zones / masks come from state.cameras). When the
 * item is a timelapse the helper hides masks via ``opts.hideMasks``
 * because a sped-up playback already has enough visual noise.
 *
 * Idempotent — calling again replaces the previous wiring cleanly.
 */
export function mountZoneOverlayForLightbox(item, opts = {}){
  unmountZoneOverlayForLightbox();
  if (!item || !item.camera_id) return;
  const wrap = document.getElementById('lightboxMediaWrap');
  if (!wrap) return;
  const video = document.getElementById('lightboxVideo');
  const img = document.getElementById('lightboxImg');
  // Prefer whichever element is currently visible — the lightbox
  // shows the <img> for photos / pre-decode, the <video> for
  // motion clips and timelapses.
  const mediaEl = (video && video.style.display !== 'none' && video.src)
    ? video
    : (img && img.style.display !== 'none' && img.src ? img : null);
  if (!mediaEl) return;
  _videoEl = mediaEl;
  const canvas = _ensureCanvas(wrap);
  const cam = (state.cameras || []).find(c => c.id === item.camera_id) || {};
  // Sanitise polygons into the shape renderZoneLayer expects —
  // both editor-source ({points:[{x,y}]}) and legacy ({poly:[...]})
  // forms come through.
  const polygons = {
    zones: (cam.zones || []).map(z => z.points || z.poly || z),
    masks: (cam.masks || []).map(m => m.points || m.poly || m),
  };
  const isTL = item.type === 'timelapse';
  const draw = () => renderZoneLayerForMediaEl(canvas, _videoEl, polygons, {
    hideMasks: opts.hideMasks ?? isTL,
  });
  // ResizeObserver — fires on every layout change of the media
  // element (window resize, address-bar collapse on iOS, modal
  // open/close, fullscreen enter/exit).
  _resizeObs = new ResizeObserver(draw);
  _resizeObs.observe(_videoEl);
  // loadedmetadata — videoWidth/videoHeight only become non-zero
  // after this fires. fittedRect handles the pre-metadata case but
  // an explicit redraw keeps the overlay in sync the moment the
  // browser knows the source dimensions.
  _onMeta = () => draw();
  _videoEl.addEventListener('loadedmetadata', _onMeta);
  if (img){
    // Same trick on the <img> for photo / snapshot playback.
    _videoEl.addEventListener('load', _onMeta);
  }
  // window resize — belt and braces for browsers where the
  // ResizeObserver on the inner element doesn't fire on viewport
  // changes that don't change the element's CSS box.
  _onResize = () => draw();
  window.addEventListener('resize', _onResize);
  // First paint.
  draw();
}

export function unmountZoneOverlayForLightbox(){
  if (_resizeObs){
    try { _resizeObs.disconnect(); } catch { /* ignore */ }
    _resizeObs = null;
  }
  if (_videoEl){
    if (_onMeta){
      _videoEl.removeEventListener('loadedmetadata', _onMeta);
      _videoEl.removeEventListener('load', _onMeta);
    }
    _videoEl = null;
    _onMeta = null;
  }
  if (_onResize){
    window.removeEventListener('resize', _onResize);
    _onResize = null;
  }
  const c = document.getElementById(_ZONE_CANVAS_ID);
  if (c) c.remove();
}

// Expose on window so lightbox.js' close path can tear down without
// importing this module directly (avoids circular load order).
window._mountZoneOverlayForLightbox = mountZoneOverlayForLightbox;
window._unmountZoneOverlayForLightbox = unmountZoneOverlayForLightbox;
