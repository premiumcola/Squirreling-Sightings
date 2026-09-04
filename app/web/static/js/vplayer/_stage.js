// ─── vplayer/_stage.js ─────────────────────────────────────────────────────
// The picture, and the layers over it. Creates the package's OWN
// <video> and <img> — not #lightboxVideo, not #lightboxImg — plus three
// absolutely positioned overlay hosts, and keeps all four aligned with
// the letterboxed picture as the box changes.
//
// The refit is the whole job. `object-fit: contain` letterboxes the
// media inside its element, so an overlay sized to the ELEMENT is
// offset from the picture by half a gutter, and an SVG with
// preserveAspectRatio letterboxes a second time inside those wrong
// bounds. core/video-fit.js's containRect answers where the pixels
// actually are; every layer is pinned to that rect.
//
// Two triggers, because either alone leaves a stale layer: a
// ResizeObserver for the box changing (rotation, the address bar
// collapsing, the panel folding open) and loadedmetadata for the SOURCE
// dimensions arriving, which on first open happens AFTER the first
// layout and would otherwise leave every layer sized to the fallback.

import { containRect } from '../core/video-fit.js';
// One positioner for every layer in the app, carrying the `inset` ban
// with it. See core/box-model.js::placeOverlayBox.
import { placeOverlay } from '../core/box-model.js';
// The refit is also the moment the crowding verdict can change, so the
// density rule rides the same trigger rather than growing a third one.
import { chromeRects, mountStripHeight } from './_density.js';

/** The layers, in paint order. Zones sit under the boxes drawn on them. */
export const VP_LAYERS = ['zones', 'trails', 'boxes'];

/** Source dimensions of whichever element currently carries pixels. */
function _sourceSize(media) {
  if (!media) return { w: 0, h: 0 };
  return {
    w: media.videoWidth || media.naturalWidth || 0,
    h: media.videoHeight || media.naturalHeight || 0,
  };
}

/**
 * Build the media elements and the layer hosts inside the frame.
 * Split out so mountStage stays well inside the 60-line ceiling.
 */
function _buildFrame(frame) {
  const video = document.createElement('video');
  video.className = 'vp-media vp-video';
  video.playsInline = true;
  // iOS needs the attribute form too — the property alone is ignored by
  // older WebKit and the clip then takes over the whole screen on play.
  video.setAttribute('playsinline', '');
  video.preload = 'metadata';
  // Endless, and deliberately NOT a switch. A clip here is a few seconds
  // of an animal doing something and watching it twice is the normal
  // case, so the operator's ruling stands as written: „die Endlosschleife
  // muss man nicht an- und ausmachen können. Das ist einfach so."
  // `loop` also suppresses `ended`, which is why the transport's
  // play/pause glyph keeps reading correctly across the wrap.
  video.loop = true;
  video.hidden = true;

  const img = document.createElement('img');
  img.className = 'vp-media vp-img';
  img.alt = '';
  img.hidden = true;

  frame.appendChild(video);
  frame.appendChild(img);

  const layers = {};
  for (const name of VP_LAYERS) {
    const host = document.createElement('div');
    host.className = `vp-layer vp-layer-${name}`;
    host.dataset.layer = name;
    frame.appendChild(host);
    layers[name] = host;
  }
  return { video, img, layers };
}

/**
 * Wire both refit triggers and return the single detach.
 *
 * Both are needed. The observer catches the BOX changing — rotation,
 * the address bar collapsing, the panel folding open. The media events
 * catch the SOURCE dimensions arriving, which on first open happens
 * after the first layout: without them every layer stays sized to the
 * pre-metadata fallback until something else happens to resize.
 */
function _installRefitTriggers(frame, media, img, refit) {
  const ro = typeof ResizeObserver === 'function' ? new ResizeObserver(() => refit()) : null;
  ro?.observe(frame);
  media.addEventListener('loadedmetadata', refit);
  // An <img> reports naturalWidth on load, not on loadedmetadata.
  img.addEventListener('load', refit);
  return () => {
    ro?.disconnect();
    media.removeEventListener('loadedmetadata', refit);
    img.removeEventListener('load', refit);
  };
}

/**
 * Release the media sources. A <video> removed with a src still set
 * keeps the connection open in some browsers, and an MJPEG <img>
 * request stays live indefinitely — one camera stream per abandoned
 * open, which is how a long session ends up starving the others.
 */
function _releaseMedia(video, img) {
  try {
    video.pause();
  } catch {
    /* never mounted a source */
  }
  video.removeAttribute('src');
  img.removeAttribute('src');
}

/**
 * Mount the stage.
 *
 * @param {HTMLElement} frame  the shell's [data-slot="frame"]
 * @param {object} cfg         normalised config from _config.js
 * @returns {object|null} stage handle
 */
export function mountStage(frame, cfg) {
  if (!frame) return null;
  const { video, img, layers } = _buildFrame(frame);

  // Which element carries pixels: a recorded clip is a <video>, the
  // live and simulation surfaces are an <img> fed by snapshots.
  const useVideo = cfg.mode === 'recorded';
  const media = useVideo ? video : img;
  media.hidden = false;

  let rect = { x: 0, y: 0, w: 0, h: 0, scale: 1 };
  const listeners = new Set();

  // The frame's own parent. Everything that floats ON the picture — the
  // layer switches, the transport, the timeline strip — is pinned to it,
  // so it is also what the density verdict has to be written onto.
  const stageEl = frame.parentElement;
  const density = mountStripHeight(stageEl);

  const refit = () => {
    const box = frame.getBoundingClientRect();
    const src = _sourceSize(media);
    rect = containRect(src.w, src.h, box.width, box.height);
    for (const name of VP_LAYERS) placeOverlay(layers[name], rect);
    density.measure();
    listeners.forEach((fn) => fn(rect));
  };

  const detach = _installRefitTriggers(frame, media, img, refit);
  refit();

  return {
    video,
    img,
    media,
    layers,
    /** Current picture rect, in frame coordinates. */
    rect: () => ({ ...rect }),
    /**
     * The on-picture chrome, in picture coordinates. The painter hands
     * it to the plate renderer so a label never lands underneath the
     * layer switches, a chevron or the play disc.
     */
    chrome: () => chromeRects(stageEl, rect),
    refit,
    /** Call fn(rect) after every refit. Returns the unsubscribe. */
    onRefit: (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    teardown: () => {
      detach();
      density.teardown();
      listeners.clear();
      _releaseMedia(video, img);
      frame.innerHTML = '';
    },
  };
}
