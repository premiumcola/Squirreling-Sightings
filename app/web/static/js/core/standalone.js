// ─── core/standalone.js ────────────────────────────────────────────────────
// PWA / iOS-Standalone detection. The app runs inside Safari's standalone
// "added to home screen" container if either:
//   • CSS display-mode media query reports "standalone" (Android, modern PWAs)
//   • navigator.standalone === true (Apple-specific iOS Safari signal)
// `is-standalone` lands on <body> exactly once at import time so CSS rules
// keyed on the class can pull stronger safe-area paddings, hide
// browser-only affordances, etc.

export const isStandalone = (
  (typeof window !== 'undefined') &&
  ((window.matchMedia?.('(display-mode: standalone)').matches)
    || window.navigator?.standalone === true)
);

function _apply(){
  if (!isStandalone) return;
  const body = document.body;
  if (body && !body.classList.contains('is-standalone')) {
    body.classList.add('is-standalone');
  }
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _apply, { once: true });
  } else {
    _apply();
  }
}
