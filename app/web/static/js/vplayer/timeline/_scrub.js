// ─── vplayer/timeline/_scrub.js ────────────────────────────────────────────
// Drag-to-seek on the rail. Ported from the recorded scrubber's
// pointer-capture drag, with every global lookup replaced by an
// argument — that is the whole change, and it is what lets one
// implementation drive both a recorded scrubber and a read-only live
// strip (omit onSeek and the drag simply never arms).
//
// POINTER CAPTURE IS THE POINT. Without it a drag dies the moment the
// finger leaves the 6 px rail, which on a phone is immediately. With
// it the element keeps receiving moves until the finger lifts anywhere
// on screen.
//
// THE PAUSE/RESUME CONTRACT. A drag that started during playback
// pauses, seeks, and resumes on release; a drag that started while
// paused leaves it paused. Getting this backwards makes a scrub either
// stutter against the running playhead or silently start playback.

/**
 * PURE: where along a rect a pointer landed, as a fraction.
 *
 * @param {number} clientX
 * @param {{left:number, width:number}} rect
 * @returns {number|null} 0..1, or null when the rect has no width —
 *   an unlaid-out rail must not resolve every drag to its left edge.
 */
export function pctFromRect(clientX, rect) {
  if (!rect || !(rect.width > 0)) return null;
  if (!Number.isFinite(clientX)) return null;
  return Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
}

/**
 * PURE: the time a pointer position seeks to.
 *
 * @returns {number|null} seconds, or null when there is nothing to
 *   seek — no width, or no duration (a live strip, or a clip whose
 *   metadata has not arrived).
 */
export function timeFromRect(clientX, rect, duration) {
  if (!(duration > 0)) return null;
  const pct = pctFromRect(clientX, rect);
  return pct == null ? null : pct * duration;
}

/**
 * Wire drag-to-seek onto an element.
 *
 * @param {HTMLElement} el
 * @param {object} opts
 * @param {() => DOMRect} opts.getRect       the rail's measured rect
 * @param {() => number} opts.getDuration    clip length in seconds
 * @param {(t: number) => void} [opts.onSeek]  omit for a read-only strip
 * @param {() => boolean} [opts.isPlaying]
 * @param {() => void} [opts.onPause]
 * @param {() => void} [opts.onResume]
 * @returns {{teardown: () => void}|null}
 */
export function attachScrub(el, opts = {}) {
  if (!el || typeof opts.onSeek !== 'function') return null;

  let resumeAfter = false;

  const seekTo = (clientX) => {
    const t = timeFromRect(clientX, opts.getRect(), opts.getDuration());
    if (t != null) opts.onSeek(t);
  };

  const onDown = (ev) => {
    ev.preventDefault();
    try {
      el.setPointerCapture(ev.pointerId);
    } catch {
      /* a browser without pointer capture still gets the seek */
    }
    resumeAfter = opts.isPlaying ? opts.isPlaying() === true : false;
    if (resumeAfter) opts.onPause?.();
    seekTo(ev.clientX);
  };

  const onMove = (ev) => {
    if (!el.hasPointerCapture?.(ev.pointerId)) return;
    seekTo(ev.clientX);
  };

  const onUp = (ev) => {
    if (el.hasPointerCapture?.(ev.pointerId)) {
      try {
        el.releasePointerCapture(ev.pointerId);
      } catch {
        /* already released */
      }
    }
    if (resumeAfter) opts.onResume?.();
    resumeAfter = false;
  };

  el.addEventListener('pointerdown', onDown);
  el.addEventListener('pointermove', onMove);
  el.addEventListener('pointerup', onUp);
  el.addEventListener('pointercancel', onUp);

  return {
    teardown: () => {
      el.removeEventListener('pointerdown', onDown);
      el.removeEventListener('pointermove', onMove);
      el.removeEventListener('pointerup', onUp);
      el.removeEventListener('pointercancel', onUp);
    },
  };
}
