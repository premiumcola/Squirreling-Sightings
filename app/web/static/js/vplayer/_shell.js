// ─── vplayer/_shell.js ─────────────────────────────────────────────────────
// The package's own root. Created with document.createElement and
// appended to document.body — it never queries #lightboxModal,
// #lightboxInner or #lightboxMediaWrap, and nothing reparents anything
// into it.
//
// That independence is the point. The previous architecture had to
// REPARENT one shared media wrap between four surfaces because
// mediathek/bbox-overlay/index.js binds loadedmetadata / play / pause /
// seeked / timeupdate plus a ResizeObserver to the fixed ids
// #lightboxVideo / #lightboxImg in a module-load IIFE that never
// unbinds. Those hooks are still installed while both players are on
// disk; they simply have nothing to say about a video this shell owns.
//
// THE KEYBOARD IS THE SAME PROBLEM. mediaview/keyboard.js installs
// document-level handlers at module scope, including an Esc/Backspace
// back-nav for the drilldown. A capture-phase listener here sees every
// key first and stops it there, so those handlers stay inert while this
// player is open without editing that file at all.

import { VP_ROOT_CLASS, VP_SHELL_HTML } from './_shell-html.js';

/** Keys the shell consumes outright while it is open. */
const _SWALLOWED = new Set([
  'Escape',
  'Backspace',
  ' ',
  'ArrowLeft',
  'ArrowRight',
  'ArrowUp',
  'ArrowDown',
  'Home',
  'End',
]);

/**
 * Is this event aimed at something that legitimately wants the key?
 * A text field, a textarea or anything contenteditable — typing must
 * never be swallowed, and neither must a browser shortcut carrying a
 * modifier.
 */
function _isTypingTarget(ev) {
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return true;
  const t = ev.target;
  if (!t || !t.tagName) return false;
  const tag = t.tagName.toUpperCase();
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || t.isContentEditable === true;
}

/**
 * Lock body scroll and return the exact undo.
 *
 * Restores the INLINE value verbatim rather than assuming it was empty:
 * another overlay may already have set one, and clobbering it is how a
 * page ends up permanently unscrollable after two modals close in the
 * wrong order.
 *
 * Deliberately not the position:fixed trick — on iOS that jumps the
 * page to the top on unlock, which is exactly the address-bar-collapse
 * class of bug this project keeps re-fixing.
 */
function _lockBodyScroll() {
  const body = document.body;
  if (!body) return () => {};
  const prevOverflow = body.style.overflow;
  const prevOverscroll = body.style.overscrollBehavior;
  body.style.overflow = 'hidden';
  body.style.overscrollBehavior = 'contain';
  return () => {
    body.style.overflow = prevOverflow;
    body.style.overscrollBehavior = prevOverscroll;
  };
}

/**
 * Install the capture-phase key handler. Returns its removal function.
 *
 * @param {(key: string, ev: KeyboardEvent) => void} onKey
 */
function _installKeyTrap(onKey) {
  const handler = (ev) => {
    if (_isTypingTarget(ev)) return;
    if (!_SWALLOWED.has(ev.key)) return;
    // Capture phase: stop it before any document-level listener that
    // was bound at module load by another surface can react.
    ev.stopPropagation();
    ev.preventDefault();
    onKey(ev.key, ev);
  };
  document.addEventListener('keydown', handler, true);
  return () => document.removeEventListener('keydown', handler, true);
}

/**
 * Build the shell and mount it.
 *
 * @param {object} cfg    normalised config from _config.js
 * @param {object} [opts]
 * @param {(key: string) => void} [opts.onKey]  key the shell swallowed
 * @returns {{root: HTMLElement, slot: (name: string) => HTMLElement|null,
 *   teardown: () => void}}
 */
export function mountShell(cfg, opts = {}) {
  const root = document.createElement('div');
  root.className = VP_ROOT_CLASS;
  root.dataset.mode = cfg.mode;
  root.setAttribute('role', 'dialog');
  root.setAttribute('aria-modal', 'true');
  root.innerHTML = VP_SHELL_HTML;
  document.body.appendChild(root);

  const unlock = _lockBodyScroll();
  const untrap = _installKeyTrap((key, ev) => opts.onKey?.(key, ev));

  let torn = false;
  return {
    root,
    slot: (name) => root.querySelector(`[data-slot="${name}"]`),
    /** Reverse mount order: key trap, scroll lock, then the DOM. */
    teardown: () => {
      if (torn) return;
      torn = true;
      untrap();
      unlock();
      root.remove();
    },
  };
}
