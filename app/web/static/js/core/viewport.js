// ─── core/viewport.js ──────────────────────────────────────────────────────
// Centralised viewport-resize listener. iOS Safari's address-bar collapse
// changes the visible height without firing window 'resize' reliably; the
// visualViewport API does fire on collapse, so we prefer it where present
// and fall back to window 'resize' otherwise. Callbacks are dispatched via
// requestAnimationFrame to coalesce bursts (visualViewport fires every
// frame during pinch-zoom or address-bar animation).
//
//   import { onViewportChange } from './core/viewport.js';
//   onViewportChange(({ width, height }) => layoutMyPanel(width, height));

const _subscribers = new Set();
let _rafScheduled = false;

function _flush() {
  _rafScheduled = false;
  const w = window.visualViewport?.width ?? window.innerWidth;
  const h = window.visualViewport?.height ?? window.innerHeight;
  for (const fn of _subscribers) {
    try {
      fn({ width: w, height: h });
    } catch {
      /* keep other subscribers alive */
    }
  }
}

function _schedule() {
  if (_rafScheduled) return;
  _rafScheduled = true;
  requestAnimationFrame(_flush);
}

if (typeof window !== 'undefined') {
  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', _schedule);
    window.visualViewport.addEventListener('scroll', _schedule);
  }
  window.addEventListener('resize', _schedule);
}

export function onViewportChange(fn) {
  _subscribers.add(fn);
  return () => _subscribers.delete(fn);
}

export function getViewportSize() {
  return {
    width: window.visualViewport?.width ?? window.innerWidth,
    height: window.visualViewport?.height ?? window.innerHeight,
  };
}
