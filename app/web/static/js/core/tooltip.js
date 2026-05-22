// ─── core/tooltip.js ───────────────────────────────────────────────────────
// Shared dark-surface tooltip used for icon-only buttons across the
// app. Reuses the `.mv-live-toggle-tip` CSS class from
// 30-lightbox-video.css so the visual matches the overlay-toggle
// popover and the status-legend popover 1:1.
//
// Two entry points:
//
//   showTooltip(target, text)
//     Position + reveal the tooltip above (or below, when there's no
//     room above) the target element. Pass null/empty text to hide.
//
//   attachHoverAndLongPress(button, getText)
//     One-call wiring for buttons that need a tooltip on desktop
//     hover (~300 ms) + touch long-press (~500 ms). `getText` is
//     either a string or a callback (button) => string so the caller
//     can read the latest label off `data-*` or live state.
//
// Module-level state means one tooltip element is reused for every
// caller. That's fine — only one tooltip can be visible at a time
// anyway, and the dom node + listeners cost is amortised over the
// page lifetime.

const _HOVER_DELAY_MS = 300;
const _LONG_PRESS_MS = 500;

let _tipEl = null;
let _hoverTimer = 0;
let _longPressTimer = 0;

function _ensureTip() {
  if (_tipEl) return _tipEl;
  _tipEl = document.createElement('div');
  _tipEl.className = 'mv-live-toggle-tip';
  _tipEl.setAttribute('role', 'tooltip');
  _tipEl.hidden = true;
  document.body.appendChild(_tipEl);
  return _tipEl;
}

export function showTooltip(target, text) {
  if (!target || !text) {
    hideTooltip();
    return;
  }
  const tip = _ensureTip();
  tip.textContent = text;
  tip.hidden = false;
  const r = target.getBoundingClientRect();
  const tipR = tip.getBoundingClientRect();
  const above = r.top - tipR.height - 10;
  const top = above >= 8 ? above : r.bottom + 10;
  const vw = window.innerWidth || document.documentElement.clientWidth;
  let left = r.left + r.width / 2 - tipR.width / 2;
  left = Math.max(8, Math.min(vw - tipR.width - 8, left));
  tip.style.top = `${Math.round(top)}px`;
  tip.style.left = `${Math.round(left)}px`;
}

export function hideTooltip() {
  if (_tipEl) _tipEl.hidden = true;
  clearTimeout(_hoverTimer);
  clearTimeout(_longPressTimer);
}

/**
 * Wire a tooltip onto an element: desktop hover (300 ms delay) +
 * touch long-press (500 ms). The caller is responsible for the
 * text source — pass a string to lock the label, or a function for
 * live re-reading (e.g. when the visible state encodes the text).
 *
 * Returns a teardown function the caller can call when the element
 * is removed from the DOM to release the listeners + any pending
 * timers.
 */
export function attachHoverAndLongPress(el, getText) {
  if (!el) return () => {};
  const _text = () => (typeof getText === 'function' ? getText(el) : getText);
  const _showSoon = () => {
    clearTimeout(_hoverTimer);
    _hoverTimer = setTimeout(() => showTooltip(el, _text()), _HOVER_DELAY_MS);
  };
  let _suppressClick = false;
  const onEnter = (ev) => {
    if (ev.pointerType !== 'mouse') return;
    _showSoon();
  };
  const onLeave = () => hideTooltip();
  const onTouchStart = () => {
    clearTimeout(_longPressTimer);
    _longPressTimer = setTimeout(() => {
      _suppressClick = true;
      showTooltip(el, _text());
    }, _LONG_PRESS_MS);
  };
  const onTouchEnd = () => clearTimeout(_longPressTimer);
  const onClick = (ev) => {
    if (_suppressClick) {
      _suppressClick = false;
      ev.preventDefault();
      ev.stopPropagation();
    }
  };
  el.addEventListener('pointerenter', onEnter);
  el.addEventListener('pointerleave', onLeave);
  el.addEventListener('touchstart', onTouchStart, { passive: true });
  el.addEventListener('touchend', onTouchEnd);
  el.addEventListener('touchcancel', onTouchEnd);
  // Click listener runs in capture phase so it can swallow the
  // synthesized click that follows a long-press. Capture is required
  // because the chip's own click handler usually `stopPropagation()`s
  // on bubble before this would have a chance to fire.
  el.addEventListener('click', onClick, true);
  return () => {
    clearTimeout(_hoverTimer);
    clearTimeout(_longPressTimer);
    el.removeEventListener('pointerenter', onEnter);
    el.removeEventListener('pointerleave', onLeave);
    el.removeEventListener('touchstart', onTouchStart);
    el.removeEventListener('touchend', onTouchEnd);
    el.removeEventListener('touchcancel', onTouchEnd);
    el.removeEventListener('click', onClick, true);
  };
}
