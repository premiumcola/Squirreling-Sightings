// ─── core/toast.js ─────────────────────────────────────────────────────────
// Toast notifications + the styled confirm modal used by every domain
// module instead of native window.confirm() (per CLAUDE.md). Both are
// exported AND attached to window so inline onclick handlers in
// dynamically-rendered template strings can still find them.
import { byId } from './dom.js';

/**
 * @param {string} msg
 * @param {string} type   info | success | warn | error
 * @param {object} [opts]
 * @param {{label:string, onClick:Function}} [opts.action]
 *   One inline button inside the toast. Added for the Netz panel's
 *   8-second "Rückgängig" after a commit: an undo has to sit ON the
 *   confirmation it undoes, and a second toast variant would have been
 *   a parallel implementation of this one.
 * @param {number} [opts.lifetime]  ms; defaults by severity.
 */
export function showToast(msg, type = 'info', opts = {}) {
  const c = byId('toastContainer');
  if (!c) return;
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  const glyphs = { warn: '!', error: '×', success: '✓', info: 'i' };
  const icon = document.createElement('span');
  icon.className = 'toast-icon';
  icon.textContent = glyphs[type] || 'i';
  const text = document.createElement('span');
  text.className = 'toast-msg';
  text.textContent = String(msg ?? '');
  const close = document.createElement('button');
  close.className = 'toast-close';
  close.textContent = '×';
  close.addEventListener('click', () => t.remove());
  t.append(icon, text);
  if (opts.action?.label) {
    const act = document.createElement('button');
    act.className = 'toast-action';
    act.type = 'button';
    act.textContent = opts.action.label;
    act.addEventListener('click', () => {
      t.remove();
      try {
        opts.action.onClick?.();
      } catch (e) {
        console.error('[toast] action failed', e);
      }
    });
    t.append(act);
  }
  t.append(close);
  c.appendChild(t);
  // Toast lifetime by severity — errors linger longest because the
  // user usually wants time to read what failed before reaching for
  // a retry. An action toast gets 8 s: long enough to notice and reach.
  const bySeverity =
    type === 'error' ? 8000 : type === 'warn' || type === 'info' ? 6000 : 4000;
  const lifetime = opts.lifetime || (opts.action ? 8000 : bySeverity);
  const dismiss = () => {
    t.classList.add('toast-out');
    t.addEventListener('animationend', () => t.remove(), { once: true });
  };
  setTimeout(dismiss, lifetime);
}

let _confirmResolve = null;
export function showConfirm(msg) {
  return new Promise((resolve) => {
    _confirmResolve = resolve;
    const modal = byId('confirmModal');
    const msgEl = byId('confirmMsg');
    if (!modal || !msgEl) {
      resolve(false);
      return;
    }
    msgEl.textContent = msg;
    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  });
}

export function _resolveConfirm(val) {
  const modal = byId('confirmModal');
  if (modal) {
    modal.classList.add('hidden');
    document.body.style.overflow = '';
  }
  if (_confirmResolve) {
    _confirmResolve(val);
    _confirmResolve = null;
  }
}

// Wire confirm-modal buttons (idempotent — guarded against the modal
// being rendered before the DOM is ready or against repeated init).
export function bindConfirmModal() {
  const okBtn = byId('confirmOk');
  const cancelBtn = byId('confirmCancel');
  const modal = byId('confirmModal');
  if (okBtn && !okBtn.dataset.wired) {
    okBtn.dataset.wired = '1';
    okBtn.addEventListener('click', () => _resolveConfirm(true));
  }
  if (cancelBtn && !cancelBtn.dataset.wired) {
    cancelBtn.dataset.wired = '1';
    cancelBtn.addEventListener('click', () => _resolveConfirm(false));
  }
  if (modal && !modal.dataset.wired) {
    modal.dataset.wired = '1';
    modal.addEventListener('click', (e) => {
      if (e.target === modal) _resolveConfirm(false);
    });
  }
}

// Legacy global bridge — inline handler attributes in the template
// (e.g. confirmOk's onclick fallback if someone wires it inline)
// look these up on window. Domain modules import the named exports
// directly; only the inline-handler path needs window.
window.showToast = showToast;
window.showConfirm = showConfirm;
