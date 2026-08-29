// ─── netz/_help.js ─────────────────────────────────────────────────────────
// The "i" button next to the Erkennungsnetz title. Content is static
// server-rendered markup in netz.html — nothing here reads netzState,
// so this module only opens/closes, matching the .modal/.hidden pattern
// every other modal in the app already uses (camera-merge.js et al.).
import { byId } from '../core/dom.js';

function _open() {
  byId('netzHelpModal')?.classList.remove('hidden');
}

function _close() {
  byId('netzHelpModal')?.classList.add('hidden');
}

export function initNetzHelp() {
  const btn = byId('netzHelpBtn');
  const modal = byId('netzHelpModal');
  if (!btn || !modal || btn.dataset.wired) return;
  btn.dataset.wired = '1';
  btn.addEventListener('click', _open);
  byId('netzHelpCloseBtn')?.addEventListener('click', _close);
  modal.addEventListener('click', (e) => {
    if (e.target === modal) _close();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !modal.classList.contains('hidden')) _close();
  });
}
