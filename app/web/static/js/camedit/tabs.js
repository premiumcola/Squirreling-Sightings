// ─── camedit/tabs.js ───────────────────────────────────────────────────────
// The cam-edit tab bar. Reset to "Allgemein" on every open, then plain
// click-to-switch. Its own module because both index.js and edit-panel.js
// need it and index.js was 919 lines against a 400-line ceiling.
import { byId } from '../core/dom.js';
import { _refreshSeverityLockState } from '../alerting.js';

export function initCameraEditTabs() {
  const bar = document.querySelector('.cam-tab-bar');
  if (!bar) return;
  // Reset to first tab
  bar.querySelectorAll('.cam-tab-btn').forEach((b) => b.classList.remove('active'));
  document.querySelectorAll('.cam-tab-panel').forEach((p) => p.classList.remove('active'));
  const first = bar.querySelector('.cam-tab-btn[data-tab="cam-tab-allgemein"]');
  if (first) first.classList.add('active');
  const firstPanel = byId('cam-tab-allgemein');
  if (firstPanel) firstPanel.classList.add('active');
  bar.querySelectorAll('.cam-tab-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      bar.querySelectorAll('.cam-tab-btn').forEach((b) => b.classList.remove('active'));
      document.querySelectorAll('.cam-tab-panel').forEach((p) => p.classList.remove('active'));
      btn.classList.add('active');
      const panel = byId(btn.dataset.tab);
      if (panel) panel.classList.add('active');
      // B2 · re-evaluate the severity-matrix locks against the LIVE
      // object-filter whenever this tab becomes active. The filter pills
      // now sit on this very tab, so the pills' own change event carries
      // most of the work; this keeps the state right after a reopen.
      if (btn.dataset.tab === 'cam-tab-alerting') _refreshSeverityLockState();
    });
  });
}
