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
// The time formatters live in core/clock-format.js and are re-exported
// here, where every existing caller and test already looks for them.
// They are FLOORED, unlike mediathek/_cards.js's card-badge `_fmtDur`,
// which rounds: a 5.6 s clip reads "0:06" there, which is right for a
// duration badge and wrong for a running clock, where it would make the
// readout jump a second early.

import { showToast } from '../../core/toast.js';
import { NATIVE_WARNING } from './_native.js';
import { isInPictureInPicture } from './_pip.js';
// Imported AND re-exported: this file uses both locally (the elapsed /
// −remaining strip below), and a re-export alone would not put them in
// its own scope — the repeat regression CLAUDE.md's refactor section
// documents.
import { clockLabel, remainingLabel } from '../../core/clock-format.js';
export { clockLabel, remainingLabel } from '../../core/clock-format.js';

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

// Small rect-in-a-rect — the house PiP glyph everywhere (system player
// affordances included), kept in the same stroke-only language as the
// rest of this file's icons rather than inventing a distinct visual idiom
// for what is, to the operator, the same kind of action as the system-
// player switch: hand the clip to a different presentation surface.
const _PIP_SVG =
  '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><rect x="12" y="11" width="7" height="6" rx="1" fill="currentColor" stroke="none"/></svg>';

function _seekBy(video, delta) {
  if (!video) return;
  const dur = Number.isFinite(video.duration) && video.duration > 0 ? video.duration : 0;
  const cur = Number.isFinite(video.currentTime) ? video.currentTime : 0;
  const next = Math.max(0, cur + delta);
  video.currentTime = dur > 0 ? Math.min(dur, next) : next;
}

function _markup(nativeAvailable, pipAvailable) {
  const nativeBtn = nativeAvailable
    ? `<button type="button" class="mv-player-native" data-act="native" ` +
      `title="Im Systemplayer öffnen — ${NATIVE_WARNING}" ` +
      `aria-label="Im Systemplayer öffnen. ${NATIVE_WARNING}">` +
      `${_EXPAND_SVG}<span>Systemplayer</span></button>`
    : '';
  // Same pill class as the system-player switch (44 px target, glass-
  // over-video look, the >=380px label-hiding rule) — a second instance
  // of "hand this off elsewhere", not a new control family. `data-on`
  // follows the loop button's precedent (_transport-controls.js) rather
  // than inventing a second toggle-state idiom.
  const pipBtn = pipAvailable
    ? `<button type="button" class="mv-player-native mv-player-pip" data-act="pip" ` +
      `data-on="0" aria-pressed="false" ` +
      `title="Bild-in-Bild — ${NATIVE_WARNING}" ` +
      `aria-label="Bild-in-Bild öffnen. ${NATIVE_WARNING}">` +
      `${_PIP_SVG}<span>Bild-in-Bild</span></button>`
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
    pipBtn +
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
 * Build the transport's single delegated click handler. Extracted out
 * of renderTransport so that function stays under the file's own
 * 60-line ceiling — the handler itself is a flat dispatch on
 * `data-act`/`data-skip`, nothing that benefits from staying inline.
 */
function _makeClickHandler(host, opts, getVideo, sync) {
  return (ev) => {
    const btn = ev.target.closest && ev.target.closest('button');
    if (!btn || !host.contains(btn)) return;
    if (typeof opts.onInteract === 'function') opts.onInteract();
    const v = getVideo();
    if (btn.dataset.skip) {
      _seekBy(v, Number(btn.dataset.skip));
    } else if (btn.dataset.act === 'play') {
      // A play() that rejects used to be swallowed whole, so a clip that
      // could not start looked exactly like a dead button — the operator's
      // report was "der Playknopf läuft nicht", with nothing on screen to
      // say why. A rejection here is always worth a word: it means no
      // source, an unsupported codec, or a gesture the browser refused.
      if (!v) {
        showToast('Kein Video geladen — die Aufnahme fehlt oder ist noch nicht bereit.', 'error');
        return;
      }
      if (v.paused || v.ended) {
        v.play().catch((err) => {
          const why = (err && (err.name || err.message)) || 'unbekannt';
          showToast(`Wiedergabe nicht möglich (${why}).`, 'error');
        });
      } else v.pause();
    } else if (btn.dataset.act === 'native' && typeof opts.onNative === 'function') {
      opts.onNative();
    } else if (btn.dataset.act === 'pip' && typeof opts.onPip === 'function') {
      opts.onPip();
    }
    sync();
  };
}

/**
 * Render the on-picture transport into ``host``.
 *
 * @param {HTMLElement} host
 * @param {Object} opts
 * @param {Function} opts.getVideo         () => HTMLVideoElement|null
 * @param {boolean}  opts.nativeAvailable  render the system-player switch
 * @param {Function} [opts.onNative]       clicked the system-player switch
 * @param {boolean}  [opts.pipAvailable]   render the Picture-in-Picture switch
 * @param {Function} [opts.onPip]          clicked the Picture-in-Picture switch
 * @param {Function} [opts.onInteract]     any control was used (re-arms
 *                                         the auto-hide idle timer)
 * @returns {{ el: HTMLElement, sync(): void, teardown(): void }|null}
 */
export function renderTransport(host, opts = {}) {
  const getVideo = opts.getVideo;
  if (!host || typeof getVideo !== 'function') return null;
  host.className = 'mv-player';
  host.innerHTML = _markup(!!opts.nativeAvailable, !!opts.pipAvailable);
  const playBtn = host.querySelector('.mv-player-play');
  const elapsedEl = host.querySelector('.mv-player-elapsed');
  const remainEl = host.querySelector('.mv-player-remain');
  const pipBtn = host.querySelector('.mv-player-pip');

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
    if (pipBtn) {
      const inPip = isInPictureInPicture(v);
      pipBtn.dataset.on = inPip ? '1' : '0';
      pipBtn.setAttribute('aria-pressed', String(inPip));
    }
  };

  const onClick = _makeClickHandler(host, opts, getVideo, sync);
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
