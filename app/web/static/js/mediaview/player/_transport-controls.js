// ─── mediaview/player/_transport-controls.js ───────────────────────────────
// Transport v2 — below-stage control row: speed / frame-step / loop /
// jump-to-detection / snapshot. Rides in the shell's [data-slot="controls"]
// row (real page flow, below the picture) rather than another
// absolutely-positioned cluster pinned over the stage — recorded/
// timelapse never populate that slot today (only live's interactive
// Stream+mode cluster does, via shell.js's _relocateControls), so this
// sidesteps the pinned-corner-collision class shell.js's own "M" note
// documents at length, rather than risking it a third time.
//
// Markup + delegated click handling mirrors _transport.js's own shape
// (one _markup() string, one host-level click listener keyed off
// data-act) — the pure/impure logic for each control lives in its own
// sibling file (_speed.js, _frame-step.js, _loop.js, _detection-nav.js,
// _snapshot.js) so each stays independently testable.

import { applySpeedChange, formatSpeed } from './_speed.js';
import { applyFrameStep } from './_frame-step.js';
import { toggleLoop } from './_loop.js';
import { applyDetectionJump } from './_detection-nav.js';
import { downloadSnapshot } from './_snapshot.js';

// Icons — thin-line stroke glyphs matching the project's house style
// (overlay-toggles.js / _transport.js's _skipSvg): stroke-only,
// currentColor, no fill except a small pivot/marker dot.
const _frameStepSvg = (back) =>
  `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" ` +
  `stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">` +
  `<polyline points="${back ? '14 6 8 12 14 18' : '10 6 16 12 10 18'}"/></svg>`;

const _SPEED_SVG =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" ' +
  'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M4 15a8 8 0 0 1 16 0"/><line x1="12" y1="15" x2="16" y2="10"/>' +
  '<circle cx="12" cy="15" r="1.2" fill="currentColor" stroke="none"/></svg>';

const _LOOP_SVG =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" ' +
  'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M4 7h13a3 3 0 0 1 3 3v2"/><polyline points="17 4 20 7 17 10"/>' +
  '<path d="M20 17H7a3 3 0 0 1-3-3v-2"/><polyline points="7 20 4 17 7 14"/></svg>';

// Chevron + bar — the standard "skip to marker/chapter" glyph, kept
// visually distinct from the plain chevron of _frameStepSvg (a tiny
// nudge) and from _transport.js's ring+numeral skip discs (a fixed
// time jump): this one jumps to a MARKED point, not a fixed offset.
const _detNavSvg = (back) =>
  `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" ` +
  `stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">` +
  (back
    ? '<polyline points="16 6 10 12 16 18"/><line x1="7" y1="5" x2="7" y2="19"/>'
    : '<polyline points="8 6 14 12 8 18"/><line x1="17" y1="5" x2="17" y2="19"/>') +
  '</svg>';

const _SNAPSHOT_SVG =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" ' +
  'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M4 8h3l2-2h6l2 2h3v11H4z"/><circle cx="12" cy="13.5" r="3.5"/></svg>';

function _markup() {
  return (
    `<button type="button" class="mv-t2-btn" data-act="frame-back" ` +
    `title="Ein Frame zurück (,)" aria-label="Ein Frame zurück">${_frameStepSvg(true)}</button>` +
    `<button type="button" class="mv-t2-btn" data-act="frame-fwd" ` +
    `title="Ein Frame vor (.)" aria-label="Ein Frame vor">${_frameStepSvg(false)}</button>` +
    `<button type="button" class="mv-t2-btn mv-t2-speed" data-act="speed" ` +
    `title="Wiedergabegeschwindigkeit (< >)" aria-label="Wiedergabegeschwindigkeit ändern">` +
    `${_SPEED_SVG}<span class="mv-t2-speed-lbl">1×</span></button>` +
    `<button type="button" class="mv-t2-btn" data-act="loop" data-on="0" ` +
    `title="Wiederholen (L)" aria-label="Clip wiederholen" aria-pressed="false">${_LOOP_SVG}</button>` +
    `<button type="button" class="mv-t2-btn" data-act="det-prev" ` +
    `title="Vorherige Erkennung ([)" aria-label="Zur vorherigen Erkennung springen">${_detNavSvg(true)}</button>` +
    `<button type="button" class="mv-t2-btn" data-act="det-next" ` +
    `title="Nächste Erkennung (])" aria-label="Zur nächsten Erkennung springen">${_detNavSvg(false)}</button>` +
    `<button type="button" class="mv-t2-btn" data-act="snapshot" ` +
    `title="Standbild speichern (S)" aria-label="Standbild als Bild speichern">${_SNAPSHOT_SVG}</button>`
  );
}

/**
 * Mount Transport v2 into the shell's controls row.
 *
 * @param {HTMLElement} host        the shell's [data-slot="controls"] node
 * @param {Object} opts
 * @param {Function} opts.getVideo  () => HTMLVideoElement|null
 * @returns {{ el: HTMLElement, sync(): void, teardown(): void }|null}
 */
export function renderTransportControls(host, opts = {}) {
  const getVideo = opts.getVideo;
  if (!host || typeof getVideo !== 'function') return null;

  const wrap = document.createElement('div');
  wrap.className = 'mv-t2';
  wrap.innerHTML = _markup();
  host.appendChild(wrap);

  // Reset to the neutral defaults on every mount. #lightboxVideo is the
  // SAME element reused across clip opens (player/index.js's own header
  // comment explains why) — without this reset a previous clip's 2x
  // speed or active loop would silently carry into an unrelated one.
  const v0 = getVideo();
  if (v0) {
    v0.playbackRate = 1;
    v0.loop = false;
  }

  const speedLbl = wrap.querySelector('.mv-t2-speed-lbl');
  const loopBtn = wrap.querySelector('[data-act="loop"]');

  const sync = () => {
    const v = getVideo();
    if (speedLbl) speedLbl.textContent = formatSpeed(v ? v.playbackRate : 1);
    if (loopBtn) {
      const on = !!(v && v.loop);
      loopBtn.dataset.on = on ? '1' : '0';
      loopBtn.setAttribute('aria-pressed', String(on));
    }
  };

  const onClick = (ev) => {
    const btn = ev.target.closest && ev.target.closest('button');
    if (!btn || !wrap.contains(btn)) return;
    const v = getVideo();
    switch (btn.dataset.act) {
      case 'frame-back':
        applyFrameStep(v, -1);
        break;
      case 'frame-fwd':
        applyFrameStep(v, 1);
        break;
      case 'speed':
        applySpeedChange(v, 1);
        break;
      case 'loop':
        toggleLoop(v);
        break;
      case 'det-prev':
        applyDetectionJump(v, -1);
        break;
      case 'det-next':
        applyDetectionJump(v, 1);
        break;
      case 'snapshot':
        downloadSnapshot(v);
        break;
      default:
        return;
    }
    sync();
  };
  wrap.addEventListener('click', onClick);

  // `ratechange` is native (fires on any playbackRate write, ours or
  // not); `mv:loopchange` is the synthetic event toggleLoop() dispatches
  // — together they keep this row's labels correct regardless of
  // whether the change came from this button row or the keyboard
  // shortcuts wired in lightbox.js.
  const video = getVideo();
  video?.addEventListener('ratechange', sync);
  video?.addEventListener('mv:loopchange', sync);
  video?.addEventListener('loadedmetadata', sync);
  sync();

  return {
    el: wrap,
    sync,
    teardown: () => {
      wrap.removeEventListener('click', onClick);
      video?.removeEventListener('ratechange', sync);
      video?.removeEventListener('mv:loopchange', sync);
      video?.removeEventListener('loadedmetadata', sync);
      wrap.remove();
    },
  };
}
