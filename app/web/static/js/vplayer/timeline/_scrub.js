// ─── vplayer/timeline/_scrub.js ────────────────────────────────────────────
// Drag-to-seek on the rail.
//
// POINTER CAPTURE IS THE POINT. Without it a drag dies the moment the
// finger leaves the 6 px rail, which on a phone is immediately. With it
// the element keeps receiving moves until the finger lifts anywhere on
// screen.
//
// THE PAUSE/RESUME CONTRACT. A drag that started during playback pauses,
// seeks, and resumes on release; a drag that started while paused leaves
// it paused. Getting this backwards makes a scrub either stutter against
// the running playhead or silently start playback.
//
// ── WHY THIS DOES NOT SEEK WHILE YOU DRAG ─────────────────────────────
//
// It used to, on every single pointermove, and that made the feature
// unusable: „Ich kann den Button auch total nur extrem buggy hin- und
// herschieben … es dauert fünf Sekunden, bis ich überhaupt den Play
// Button hin- und herschieben kann mit der Maus."
//
// A mouse emits pointermove far faster than the screen refreshes, and
// each of those calls set `video.currentTime`. Seeking an inter-coded
// MP4 means decoding from the nearest keyframe, so every one of those
// costs real time; the browser queues them and the picture arrives
// seconds behind the finger. The handle looked stuck because it was
// waiting on a backlog of seeks nobody wanted.
//
// So the drag moves two cheap things — the playhead marker and the
// filmstrip preview — and the video is seeked EXACTLY ONCE, on release.
// That is what the sprite sheet is for: scrubbing shows the sheet, not
// the decoder. `onPreview` gets every position; `onSeek` gets one.

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
 * @param {(t: number, x: number, phase: 'start'|'move'|'end') => void} [opts.onPreview]
 *        every drag position, cheap — the playhead marker and the
 *        filmstrip bubble. Called on the caller's own frame budget.
 * @param {() => boolean} [opts.isPlaying]
 * @param {() => void} [opts.onPause]
 * @param {() => void} [opts.onResume]
 * @returns {{teardown: () => void}|null}
 */
export function attachScrub(el, opts = {}) {
  if (!el || typeof opts.onSeek !== 'function') return null;

  let resumeAfter = false;
  let lastTime = null;

  /** The time under the pointer, or null when there is nothing to seek. */
  const timeAt = (clientX) => timeFromRect(clientX, opts.getRect(), opts.getDuration());

  /** Rail-relative x, for placing the preview bubble. */
  const localX = (clientX) => clientX - (opts.getRect()?.left || 0);

  const onDown = (ev) => {
    ev.preventDefault();
    try {
      el.setPointerCapture(ev.pointerId);
    } catch {
      /* a browser without pointer capture still gets the seek */
    }
    resumeAfter = opts.isPlaying ? opts.isPlaying() === true : false;
    if (resumeAfter) opts.onPause?.();
    const t = timeAt(ev.clientX);
    if (t == null) return;
    lastTime = t;
    opts.onPreview?.(t, localX(ev.clientX), 'start');
  };

  const onMove = (ev) => {
    if (!el.hasPointerCapture?.(ev.pointerId)) return;
    const t = timeAt(ev.clientX);
    if (t == null) return;
    lastTime = t;
    // Preview only. See the header: seeking here is what made the drag
    // feel broken.
    opts.onPreview?.(t, localX(ev.clientX), 'move');
  };

  const onUp = (ev) => {
    if (el.hasPointerCapture?.(ev.pointerId)) {
      try {
        el.releasePointerCapture(ev.pointerId);
      } catch {
        /* already released */
      }
    }
    // The one seek of the whole gesture. A click without any move lands
    // here too, having gone through onDown, so a plain tap on the rail
    // still jumps — it just jumps once.
    const t = timeAt(ev.clientX);
    const target = t == null ? lastTime : t;
    if (target != null) opts.onSeek(target);
    opts.onPreview?.(target ?? 0, localX(ev.clientX), 'end');
    lastTime = null;
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
