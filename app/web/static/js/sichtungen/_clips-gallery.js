// ─── sichtungen/_clips-gallery.js ────────────────────────────────────────
// "Eigene Aufnahmen" beside a species dossier: ONE clip at a time in a
// box as tall as the dossier card next to it, paged with a left/right
// arrow, and played IN PLACE.
//
// Was a grid of small cards. That grid replaced an even earlier
// single-full-width-video layout, and neither read well here: this
// column sits next to a tall dossier card, so a row of small tiles
// leaves the lower two thirds of the column empty ("da ist ja viel
// Freiraum"), while one giant clip wasted it the other way. A gallery
// fills the column with the clip the operator is actually looking at
// and keeps the rest one tap away.
//
// In-page play, deliberately: tapping the poster swaps a <video> into
// the SAME box instead of opening the lightbox
// (library/_bind.js::_registerMotionItems installs that opener as an
// inline onclick on every .media-card). Comparing a recording against
// the reference photos two columns over is the whole point of this
// panel; a modal covering both defeats it.
//
// The card markup itself is still mediathek/_cards.js's — this module
// only re-hosts it. Species chip, date, duration, size and the
// confirmed check therefore stay exactly what they are everywhere else,
// and there is no second card renderer to keep in sync.
import { isIOS } from '../core/ios-video.js';
import { mediaCardHTML } from '../mediathek/_cards.js';
import { adaptMotionItem } from '../library/_motion-adapter.js';
import { clampIndex, clipVideoUrl, clipsMessageHtml } from './_clips-helpers.js';

const _ARROW = (dir) =>
  `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${
    dir === 'prev' ? 'M15 5l-7 7 7 7' : 'M9 5l7 7-7 7'
  }"/></svg>`;

function _counterHtml(idx, total) {
  if (total < 2) return '';
  return `<span class="sd-gal-count">${idx + 1} / ${total}</span>`;
}

function _navHtml(idx, total) {
  if (total < 2) return '';
  const btn = (dir, disabled, label) =>
    `<button type="button" class="sd-gal-nav sd-gal-nav--${dir}" data-gal-nav="${dir}"
      ${disabled ? 'disabled' : ''} aria-label="${label}" title="${label}">${_ARROW(dir)}</button>`;
  return (
    btn('prev', idx === 0, 'Vorherige Aufnahme') +
    btn('next', idx === total - 1, 'Nächste Aufnahme')
  );
}

/**
 * Render the gallery for `items` (raw /api/library motion items) into
 * `host`, showing `idx`. Re-rendered wholesale per page turn — a clip
 * box holds at most one <video>, so replacing the markup is also what
 * tears the previous clip's playback down.
 */
export function renderClipsGallery(host, items, idx = 0) {
  if (!host) return;
  const total = items.length;
  if (!total) {
    host.innerHTML = clipsMessageHtml('Noch keine eigenen Aufnahmen dieser Art.');
    return;
  }
  const at = clampIndex(idx, total);
  host.dataset.galIdx = String(at);
  host.innerHTML = `<div class="sd-gal-stage">${mediaCardHTML(adaptMotionItem(items[at]))}</div>
    ${_navHtml(at, total)}
    ${_counterHtml(at, total)}`;
  _wireStage(host, items, at);
}

function _go(host, items, to) {
  renderClipsGallery(host, items, clampIndex(to, items.length));
}

// Swap the poster for a real <video> inside the same box. The card's
// own inline onclick (window._openMediaItem → lightbox) is removed
// first: leaving it would open the modal on the very tap that is
// supposed to keep playback in the page.
function _playInPlace(wrap, item) {
  const src = clipVideoUrl(item);
  if (!src) return;
  wrap.removeAttribute('onclick');
  const video = document.createElement('video');
  video.className = 'sd-gal-video';
  video.src = src;
  video.controls = true;
  video.autoplay = true;
  video.playsInline = true;
  // Same rule the recorded player applies (mediaview/recorded-shell-
  // compose.js): everywhere but iOS, keep the clip out of the browser's
  // own Picture-in-Picture detach affordance; on iOS native video
  // behaviour is the established exception.
  video.disablePictureInPicture = !isIOS;
  wrap.replaceChildren(video);
  video.play().catch(() => {});
}

function _wireStage(host, items, at) {
  host.querySelectorAll('[data-gal-nav]').forEach((btn) => {
    btn.addEventListener('click', (ev) => {
      ev.stopPropagation();
      _go(host, items, at + (btn.dataset.galNav === 'next' ? 1 : -1));
    });
  });
  const wrap = host.querySelector('.mmc-img-wrap');
  const item = adaptMotionItem(items[at]);
  if (wrap && clipVideoUrl(item)) {
    wrap.removeAttribute('onclick');
    wrap.addEventListener('click', () => _playInPlace(wrap, item));
  }
  _wireSwipe(host, items, at);
}

// Horizontal swipe pages the gallery. Guarded on the gesture actually
// being horizontal so a vertical page scroll started on the clip still
// scrolls; passive listeners, so it never blocks that scroll.
function _wireSwipe(host, items, at) {
  if (items.length < 2) return;
  let x0 = null;
  let y0 = null;
  host.addEventListener(
    'touchstart',
    (ev) => {
      const t = ev.changedTouches[0];
      x0 = t.clientX;
      y0 = t.clientY;
    },
    { passive: true },
  );
  host.addEventListener(
    'touchend',
    (ev) => {
      if (x0 === null) return;
      const t = ev.changedTouches[0];
      const dx = t.clientX - x0;
      const dy = t.clientY - y0;
      x0 = null;
      if (Math.abs(dx) < 45 || Math.abs(dx) <= Math.abs(dy)) return;
      _go(host, items, at + (dx < 0 ? 1 : -1));
    },
    { passive: true },
  );
}
