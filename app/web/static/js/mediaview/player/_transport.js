// ─── mediaview/player/_transport.js ────────────────────────────────────────
// The controls that ride ON the picture, in the native player's visual
// language: a generous centre transport (−10 s · play/pause · +10 s) as
// circular translucent discs, and a bottom strip with the elapsed /
// −remaining pair plus the switch to the system player.
//
// What is deliberately NOT here: a progress track. The swimlane below
// the stage already owns the time axis — its scrub bar, its pre-/post-
// roll bands and its play cursor are the same information, and CLAUDE.md
// forbids showing a thing twice. What the swimlane never had is a
// readout in seconds, which is exactly the half the native player is
// copied for. `#lbScrubPlay` (the swimlane's own play button) is hidden
// in this mode by 30h for the same reason — the centre disc is the one
// play/pause now.
//
// The time formatter is local on purpose: orchestration.js's card-badge
// `fmtDur` ROUNDS seconds (a 5.6 s clip reads "0:06"), which is right for
// a duration badge and wrong for a running clock, where it would make the
// readout jump a second early.

import { NATIVE_WARNING } from './_native.js';

const _PLAY_SVG =
  '<svg viewBox="0 0 24 24" width="30" height="30" fill="currentColor" aria-hidden="true"><path d="M7 5l13 7-13 7z"/></svg>';
const _PAUSE_SVG =
  '<svg viewBox="0 0 24 24" width="30" height="30" fill="currentColor" aria-hidden="true"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>';

// Ring-with-a-10 skip glyphs. Stroke-only ring + a filled numeral, which
// is the project's thin-line chrome idiom (overlay-toggles.js) rather
// than Apple's solid glyph.
const _skipSvg = (back) => {
  const ring = back
    ? '<path d="M12 5a7 7 0 1 0 7 7"/><polyline points="12 2 8.4 5 12 8"/>'
    : '<path d="M12 5a7 7 0 1 1-7 7"/><polyline points="12 2 15.6 5 12 8"/>';
  return (
    '<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" ' +
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    ring +
    '<text x="12" y="16.4" text-anchor="middle" font-size="8.5" font-weight="700" ' +
    'fill="currentColor" stroke="none" font-family="system-ui, sans-serif">10</text></svg>'
  );
};

const _EXPAND_SVG =
  '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>';

/** Seconds → `m:ss`, floored (a running clock, not a rounded duration). */
export function clockLabel(seconds) {
  const s = Number.isFinite(seconds) && seconds > 0 ? Math.floor(seconds) : 0;
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/** Time left, rendered the way the native player does — U+2212 prefix. */
export function remainingLabel(current, duration) {
  const dur = Number.isFinite(duration) && duration > 0 ? duration : 0;
  const cur = Number.isFinite(current) && current > 0 ? current : 0;
  return `−${clockLabel(Math.max(0, dur - cur))}`;
}

function _seekBy(video, delta) {
  if (!video) return;
  const dur = Number.isFinite(video.duration) && video.duration > 0 ? video.duration : 0;
  const cur = Number.isFinite(video.currentTime) ? video.currentTime : 0;
  const next = Math.max(0, cur + delta);
  video.currentTime = dur > 0 ? Math.min(dur, next) : next;
}

function _markup(nativeAvailable) {
  const nativeBtn = nativeAvailable
    ? `<button type="button" class="mv-player-native" data-act="native" ` +
      `title="Im Systemplayer öffnen — ${NATIVE_WARNING}" ` +
      `aria-label="Im Systemplayer öffnen. ${NATIVE_WARNING}">` +
      `${_EXPAND_SVG}<span>Systemplayer</span></button>`
    : '';
  return (
    `<div class="mv-player-center">` +
    `<button type="button" class="mv-player-btn mv-player-skip" data-skip="-10" ` +
    `aria-label="10 Sekunden zurück" title="10 s zurück">${_skipSvg(true)}</button>` +
    `<button type="button" class="mv-player-btn mv-player-play" data-act="play" ` +
    `aria-label="Abspielen / Pause" title="Abspielen / Pause">${_PLAY_SVG}</button>` +
    `<button type="button" class="mv-player-btn mv-player-skip" data-skip="10" ` +
    `aria-label="10 Sekunden vor" title="10 s vor">${_skipSvg(false)}</button>` +
    `</div>` +
    `<div class="mv-player-timebar">` +
    `<span class="mv-player-t mv-player-elapsed">0:00</span>` +
    `<span class="mv-player-spacer"></span>` +
    `<span class="mv-player-t mv-player-remain">−0:00</span>` +
    nativeBtn +
    `</div>`
  );
}

const _MEDIA_EVENTS = [
  'loadedmetadata',
  'durationchange',
  'timeupdate',
  'play',
  'playing',
  'pause',
  'ended',
  'seeking',
  'seeked',
];

/**
 * Render the on-picture transport into ``host``.
 *
 * @param {HTMLElement} host
 * @param {Object} opts
 * @param {Function} opts.getVideo         () => HTMLVideoElement|null
 * @param {boolean}  opts.nativeAvailable  render the system-player switch
 * @param {Function} [opts.onNative]       clicked the system-player switch
 * @param {Function} [opts.onInteract]     any control was used (re-arms
 *                                         the auto-hide idle timer)
 * @returns {{ el: HTMLElement, sync(): void, teardown(): void }|null}
 */
export function renderTransport(host, opts = {}) {
  const getVideo = opts.getVideo;
  if (!host || typeof getVideo !== 'function') return null;
  host.className = 'mv-player';
  host.innerHTML = _markup(!!opts.nativeAvailable);
  const playBtn = host.querySelector('.mv-player-play');
  const elapsedEl = host.querySelector('.mv-player-elapsed');
  const remainEl = host.querySelector('.mv-player-remain');

  // `timeupdate` fires ~4× a second, so every write here is guarded by a
  // comparison: re-assigning innerHTML would rebuild the play glyph's SVG
  // four times a second for a picture that did not change.
  let shownPlaying = null;
  const setText = (el, text) => {
    if (el && el.textContent !== text) el.textContent = text;
  };
  const sync = () => {
    const v = getVideo();
    const playing = !!v && !v.paused && !v.ended;
    if (playBtn && playing !== shownPlaying) {
      playBtn.innerHTML = playing ? _PAUSE_SVG : _PLAY_SVG;
      shownPlaying = playing;
    }
    setText(elapsedEl, clockLabel(v ? v.currentTime : 0));
    setText(remainEl, remainingLabel(v ? v.currentTime : 0, v ? v.duration : 0));
  };

  const onClick = (ev) => {
    const btn = ev.target.closest && ev.target.closest('button');
    if (!btn || !host.contains(btn)) return;
    if (typeof opts.onInteract === 'function') opts.onInteract();
    const v = getVideo();
    if (btn.dataset.skip) {
      _seekBy(v, Number(btn.dataset.skip));
    } else if (btn.dataset.act === 'play') {
      if (!v) return;
      if (v.paused || v.ended) v.play().catch(() => {});
      else v.pause();
    } else if (btn.dataset.act === 'native' && typeof opts.onNative === 'function') {
      opts.onNative();
    }
    sync();
  };
  host.addEventListener('click', onClick);

  const video = getVideo();
  for (const ev of _MEDIA_EVENTS) video?.addEventListener(ev, sync);
  sync();

  return {
    el: host,
    sync,
    teardown: () => {
      host.removeEventListener('click', onClick);
      for (const ev of _MEDIA_EVENTS) video?.removeEventListener(ev, sync);
      host.innerHTML = '';
    },
  };
}
