// ─── mediaview/player/_loop.js ─────────────────────────────────────────────
// Loop-the-current-clip toggle. Whole-clip repeat rather than a bounded
// in/out-point loop — the operator's actual use case here is "watch this
// short motion clip on repeat while I look at the bboxes/trails", not
// scrubbing a sub-range of a longer recording; a marker-pair UI would be
// disproportionate scope for what a plain `video.loop = true` already
// gives natively (the browser handles the seek-back-to-0 itself, no
// manual `ended`-listener seeking needed — and `loop:true` suppresses
// the native `ended` event entirely, so nothing else in this codebase
// that listens for `ended` needs to change).
//
// Not persisted across clips, for the same reason speed isn't (see
// _speed.js's header comment) — #lightboxVideo is reused across opens,
// so _transport-controls.js resets `loop` to false on every mount.

/**
 * Impure — flips video.loop and returns the new value.
 *
 * There is no native change event for the `loop` property (unlike
 * `playbackRate`, which fires `ratechange`), so this dispatches a small
 * synthetic event on the video element itself. Both the on-picture
 * button (_transport-controls.js) and the keyboard shortcut (wired
 * through lightbox.js) call THIS function rather than writing
 * `video.loop` directly, so whichever one fires, the mounted button's
 * `sync()` — listening for `mv:loopchange` — stays correct without
 * either caller needing a reference to the other's DOM.
 */
export function toggleLoop(video) {
  if (!video) return false;
  video.loop = !video.loop;
  if (typeof video.dispatchEvent === 'function') {
    video.dispatchEvent(new Event('mv:loopchange'));
  }
  return video.loop;
}
