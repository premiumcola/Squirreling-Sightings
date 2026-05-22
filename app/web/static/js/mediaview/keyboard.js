// ─── mediaview/keyboard.js ─────────────────────────────────────────────────
// Window keydown listener active while the MediaView modal is mounted.
// Three shortcuts — Space (play/pause), ArrowLeft (seek -5 s, clamp at
// 0), ArrowRight (seek +5 s, clamp at duration). All three call
// preventDefault so they don't trip the page-scroll / radio-button
// defaults. Ignored when the focused element is INPUT, TEXTAREA,
// SELECT, or contenteditable — text-entry inside a future panel tab
// keeps its native key behaviour.
//
// `install` returns a teardown function the shell calls on unmount.
// One install / teardown pair per shell mount keeps the listener from
// leaking across the modal lifecycle. The listener attaches to
// `window` instead of `document` so an outer modal layer (e.g. an
// iOS native player overlay) doesn't intercept the events before we
// see them.

const _FORM_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT']);

function _isFormFocus(target) {
  if (!target) return false;
  if (_FORM_TAGS.has(target.tagName)) return true;
  if (target.isContentEditable) return true;
  return false;
}

export function installMediaViewKeyboard(getVideoEl) {
  if (typeof getVideoEl !== 'function') {
    throw new Error('installMediaViewKeyboard: pass a getVideoEl() callback');
  }
  const onKey = (e) => {
    if (_isFormFocus(e.target)) return;
    const video = getVideoEl();
    if (!video) return;
    if (e.key === ' ') {
      e.preventDefault();
      if (video.paused || video.ended) {
        video.play().catch(() => {});
      } else {
        video.pause();
      }
      return;
    }
    if (e.key === 'ArrowLeft') {
      e.preventDefault();
      video.currentTime = Math.max(0, (video.currentTime || 0) - 5);
      return;
    }
    if (e.key === 'ArrowRight') {
      e.preventDefault();
      const dur = Number.isFinite(video.duration) ? video.duration : 0;
      const next = (video.currentTime || 0) + 5;
      video.currentTime = dur > 0 ? Math.min(dur, next) : next;
    }
  };
  window.addEventListener('keydown', onKey);
  return () => window.removeEventListener('keydown', onKey);
}
