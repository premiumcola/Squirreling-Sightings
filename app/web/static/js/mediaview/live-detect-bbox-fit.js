// ─── mediaview/live-detect-bbox-fit.js ─────────────────────────────────────
// Letterbox positioner for the live-detect overlay layers (bboxes,
// trails). Every overlay SVG must cover the IMAGE's visible rect, not
// the whole host element: the snapshot <img> uses object-fit:contain,
// so its on-screen rect is letterboxed inside the host. Without this
// correction the SVG covers the host and preserveAspectRatio:meet
// letterboxes a SECOND time inside those bounds — boxes land in the
// wrong place, or off-screen entirely.
//
// CRITICAL · never write `el.style.inset` here. `inset` is the
// shorthand for top/right/bottom/left, so assigning it AFTER the
// longhands silently resets left/top back to `auto` and the overlay
// falls to its static position — below the picture, clipped away by
// the host's overflow:hidden. That is exactly the "no bboxes in the
// simulation view" bug. _placeOverlay writes the four longhands and
// nothing else; keep it that way.

import { byId } from '../core/dom.js';
import { containRect, fittedRect } from '../core/video-fit.js';
import { zoneEl } from './live-detect-skeleton.js';
import { S } from './live-detect-state.js';

function _px(v) {
  return typeof v === 'number' ? `${v}px` : v;
}

/** Pin an absolutely-positioned overlay to an explicit rect. */
export function _placeOverlay(el, left, top, width, height) {
  const s = el.style;
  s.left = _px(left);
  s.top = _px(top);
  s.right = 'auto';
  s.bottom = 'auto';
  s.width = _px(width);
  s.height = _px(height);
}

// B19' · which media element currently carries pixels. Video counts
// only when it is displayed AND has decoded a frame (readyState ≥ 2 =
// HAVE_CURRENT_DATA); the <img> counts unless the browser is still
// fetching its first byte. Rejection reasons are stashed on S so the
// MEDIA debug row can show WHY a candidate was skipped.
function _pickLiveMediaEl() {
  const videoEl = byId('lightboxVideo');
  const imgEl = byId('lightboxImg');
  let videoRejected = null;
  if (!videoEl) videoRejected = 'no-el';
  else if (videoEl.style.display === 'none') videoRejected = 'display=none';
  else if (!videoEl.videoWidth)
    videoRejected = `videoWidth=0 readyState=${videoEl.readyState || 0}`;
  else if ((videoEl.readyState || 0) < 2) videoRejected = `readyState=${videoEl.readyState || 0}`;
  let imgRejected = null;
  if (!imgEl) imgRejected = 'no-el';
  else if (imgEl.style.display === 'none') imgRejected = 'display=none';
  else if ((imgEl.naturalWidth || 0) === 0 && !imgEl.complete) {
    imgRejected = 'naturalWidth=0 complete=false';
  }
  S.lastVideoRejected = videoRejected;
  S.lastImgRejected = imgRejected;
  if (!videoRejected) return videoEl;
  return imgRejected ? null : imgEl;
}

// The media element hasn't reported usable dimensions yet (first tick,
// or an MJPEG <img> Safari refuses to measure). We DO know the source
// aspect from the backend's frame_size, so reproduce object-fit:contain
// against the host box ourselves — fit inside AND centre, so a non-16:9
// camera doesn't get pinned to the top-left corner.
function _aspectFallback(hostBox) {
  const fs = S.session?.lastFrameSize;
  const known = !!(fs && fs.w > 0 && fs.h > 0);
  // containRect's own degenerate branch IS the "full host box" answer,
  // so both cases are one call; only the debug label differs.
  const r = containRect(known ? fs.w : 0, known ? fs.h : 0, hostBox.width, hostBox.height);
  return {
    dx: r.x,
    dy: r.y,
    w: r.w,
    h: r.h,
    branch: known ? 'wrap-fallback-aspect' : 'wrap-fallback-full',
  };
}

/**
 * Align ``svg`` with the visible media rect inside its own parent.
 * Handles both the legacy 5-zone layout (zone-video is exactly the
 * media box → plain fill) and the MediaView shell (the overlay lives
 * in #lightboxMediaWrap and needs the delta math).
 */
export function _positionSvgOverImage(svg) {
  // Fast path — inside zone-video the host IS the media box (16:9,
  // the media element fills it identically), so a plain fill is right
  // and the SVG's own preserveAspectRatio handles a source mismatch.
  const zoneVid = zoneEl('video');
  if (zoneVid && svg.parentElement === zoneVid) {
    _placeOverlay(svg, 0, 0, '100%', '100%');
    S.lastVideoRejected = null;
    S.lastImgRejected = null;
    _setMediaBranch('zone-video-fill');
    return;
  }
  const host = svg.parentElement || byId('lightboxMediaWrap');
  if (!host) {
    S.lastVideoRejected = null;
    S.lastImgRejected = null;
    _setMediaBranch('skipped-no-wrap');
    return;
  }
  const hostBox = host.getBoundingClientRect();
  if (hostBox.width <= 0 || hostBox.height <= 0) {
    _setMediaBranch('skipped-no-wrap');
    return;
  }
  const mediaEl = _pickLiveMediaEl();
  const mediaBox = mediaEl ? mediaEl.getBoundingClientRect() : null;
  let rect = null;
  if (mediaBox && mediaBox.width > 0 && mediaBox.height > 0) {
    const fit = fittedRect(mediaEl);
    if (fit.w > 0 && fit.h > 0) {
      rect = {
        dx: mediaBox.left - hostBox.left + fit.x,
        dy: mediaBox.top - hostBox.top + fit.y,
        w: fit.w,
        h: fit.h,
        branch: mediaEl.tagName === 'VIDEO' ? 'video-rect' : 'img-rect',
      };
    }
  }
  if (!rect) rect = _aspectFallback(hostBox);
  _placeOverlay(svg, rect.dx, rect.dy, rect.w, rect.h);
  _setMediaBranch(rect.branch);
}

// B19 / B19' · stash the branch _positionSvgOverImage last took so the
// next _refreshMediaRow() pickup includes it without an extra plumbing
// arg. Plain scratch — the positioner writes it, the debug row reads it.
export function _setMediaBranch(branch) {
  S.lastMediaBranch = branch;
}
