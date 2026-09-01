// ─── netz/index.js ─────────────────────────────────────────────────────────
// Erkennungsprofil — public API + boot wiring.
//
// One panel per camera, mounted beside that camera's own Live-Feed tile
// (see dashboard.js's `.cam-net-slot` and netz/_panel.js's mount logic).
// There is no shared page-level view to route between any more — the old
// `#netz` section with its camera-chip switcher is gone.
//
//   #netz?tab=verlauf&filter=offen  → the 07:00 Telegram question's
//                                     target (built server-side in
//                                     telegram_bot/_outbound/_question.py)
//
// That deep link predates this reshape and already sits in messages the
// bot has sent — it has to keep working even though there is no single
// "Verlauf page" to route to any more. `_openQuestionsDeepLink` below
// scrolls to Live-Feed and switches every panel that actually HAS an open
// question into its own Verlauf tab, filtered to "nur offen" — the
// cross-camera digest the link always meant, just landing on N panels
// instead of one shared list.

import { byId } from '../core/dom.js';
import { state } from '../core/state.js';
import { fetchArchive, fetchState } from './_api.js';
import {
  ensurePanelsMounted,
  initCombosInfo,
  initGroupLegend,
  redrawOnResize,
  renderPanel,
} from './_panel.js';
import { archiveFilterFor, netzState, setView } from './_state.js';

/** Fetch net state for any camera netzState doesn't already have a cached
 *  answer for. Safe to call repeatedly (every dashboard render/poll) —
 *  already-cached cameras are skipped, so this is a no-op most of the
 *  time and only does work right after a camera list change. */
async function _fetchMissingStates(cams) {
  const missing = cams.filter((c) => !netzState.states[c.id]);
  if (!missing.length) return;
  const results = await Promise.all(missing.map((c) => fetchState(c.id)));
  results.forEach((r) => {
    if (r && r.ok) netzState.states[r.cam_id] = r;
  });
}

// Fires once, the first time initNetPanels() has actually populated
// netzState (first boot, not every 3 s poll re-render) — a #netz deep
// link that arrives before that first pass has run would find
// netzState.cameras empty and silently do nothing.
let _bootDeepLinkArmed = true;

/** Boot + keep-alive for the per-camera panels. Called once from
 *  live-update.js's loadAll() and again on every dashboard render/poll
 *  (dashboard.js), so a camera added at runtime gets its panel without a
 *  page reload. Cheap on repeat calls — see `_fetchMissingStates`. */
export async function initNetPanels() {
  const cams = (state.cameras || []).map((c) => ({ id: c.id, name: c.name }));
  netzState.cameras = cams;
  await _fetchMissingStates(cams);
  ensurePanelsMounted();
  initCombosInfo();
  initGroupLegend();
  if (_bootDeepLinkArmed) {
    _bootDeepLinkArmed = false;
    _openQuestionsDeepLink();
  }
}
window.initNetPanels = initNetPanels;

// ── the bot's "offene Fragen" deep link ──────────────────────────────────

async function _openQuestionsDeepLink() {
  const h = location.hash || '';
  if (!h.startsWith('#netz')) return;
  const q = h.includes('?') ? new URLSearchParams(h.slice(h.indexOf('?') + 1)) : null;
  if (q?.get('tab') !== 'verlauf') return;
  byId('dashboard')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  if (q?.get('filter') !== 'offen') return;
  const res = await fetchArchive({ open: true });
  const camIds = new Set((res.ok ? res.items || [] : []).map((r) => r.cam_id).filter(Boolean));
  camIds.forEach((camId) => {
    if (!netzState.cameras.some((c) => c.id === camId)) return;
    archiveFilterFor(camId).open = true;
    setView(camId, 'verlauf');
    renderPanel(camId);
  });
}
// A hashchange after boot (e.g. the operator follows another #netz link
// from within the already-open app) always re-runs the check — only the
// very first, pre-boot arrival needs the `_bootDeepLinkArmed` gate above.
window.addEventListener('hashchange', () => {
  _openQuestionsDeepLink();
});

// Re-draw on resize: the radar is drawn at its box's px size, so a
// rotation or a window drag needs a repaint (the per-slot ResizeObserver
// in _panel.js catches the same and more; both go through one size check,
// so a resize that leaves the box alone costs nothing). Debounced, and
// skipped mid-drag.
let _resizeTimer = null;
window.addEventListener(
  'resize',
  () => {
    if (_resizeTimer) clearTimeout(_resizeTimer);
    _resizeTimer = setTimeout(redrawOnResize, 180);
  },
  { passive: true },
);
