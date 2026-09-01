// ─── netz/_panel.js ────────────────────────────────────────────────────────
// Composition + mount lifecycle for the per-camera Erkennungsprofil panel.
//
// Replaces the old single `#netz` section with a camera-chip switcher: one
// panel per camera now, each mounted beside that camera's own Live-Feed
// tile (see dashboard.js's `.cam-net-slot`, one per `.cv-card`). There is
// no shared "current camera" any more — every render/bind call here takes
// an explicit `camId` and reads/writes only that camera's slice of
// `netzState`.
//
// A panel's DOM lives OUTSIDE the poll-refreshed `#cameraCards` innerHTML
// rebuild path: dashboard.js's renderDashboard() captures each existing
// `.cam-net-slot` before it resets the grid's innerHTML and splices it
// back into its camera's freshly-templated (empty) replacement slot, so a
// panel only repaints when THIS module says so — never as a side effect
// of the 3 s camera-tile poll. That is what keeps an in-progress radar
// drag (netz/_tune_drag.js) or an open Verlauf list from being wiped out
// from underneath the operator every few seconds.
import { byId, esc } from '../core/dom.js';
import { showToast } from '../core/toast.js';
import { getCameraColor, getCameraIcon } from '../core/icons.js';
import { fetchArchive, fetchArchiveRecord } from './_api.js';
import { bindNetBody, combosHtml, frozenListHtml, netBodyHtml } from './_cards.js';
import { tuneGroupLegendHtml } from './_tune_radar.js';
import { bindTuneDrag, isTuneDragging } from './_tune_drag.js';
import { renderArchiveDetail } from './_archive_detail.js';
import { renderArchiveList } from './_archive_list.js';
import {
  archiveFilterFor,
  archiveViewFor,
  camState,
  netzState,
  setArchiveView,
  setView,
  viewFor,
} from './_state.js';

const _ROLE_DE = { security: 'Sicherheit', wildlife: 'Wildtiere', garden: 'Garten' };

const _HIST_ICON =
  `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" ` +
  `stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">` +
  `<path d="M3 12a9 9 0 1 0 3-6.7"/><polyline points="3 4 3 9 8 9"/></svg>`;

const _INFO_ICON =
  `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" ` +
  `stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">` +
  `<circle cx="12" cy="12" r="9"/><line x1="12" y1="11" x2="12" y2="16"/>` +
  `<line x1="12" y1="8" x2="12" y2="8"/></svg>`;

function _slotFor(camId) {
  return byId('cameraCards')?.querySelector(
    `.cam-net-slot[data-camid="${CSS.escape(camId)}"]`,
  );
}

// ── panel shell ─────────────────────────────────────────────────────────

function _headerHtml(cam, camId) {
  const st = camState(camId);
  const role = st ? _ROLE_DE[st.role] || st.role || '' : '';
  const inVerlauf = viewFor(camId) === 'verlauf';
  const frozen = frozenListHtml(camId);
  return (
    `<header class="netz-card-hd">` +
    `<span class="netz-card-ic" style="color:${getCameraColor(cam)}" aria-hidden="true">` +
    `${getCameraIcon(cam.name || camId)}</span>` +
    `<h4>${esc(cam.name)}</h4>` +
    (role ? `<span class="netz-card-role">${esc(role)}</span>` : '') +
    `<button type="button" class="netz-view-btn" data-netz-toggle-verlauf ` +
    `aria-pressed="${inVerlauf ? 'true' : 'false'}" ` +
    `aria-label="${inVerlauf ? 'Zurück zu den Netzen' : 'Verlauf'}" ` +
    `title="${inVerlauf ? 'Zurück zu den Netzen' : 'Verlauf'}">${_HIST_ICON}</button>` +
    (frozen
      ? `<button type="button" class="netz-view-btn" data-netz-toggle-frozen ` +
        `aria-expanded="false" aria-controls="netzFrozenBox-${esc(camId)}" ` +
        `aria-label="Werte, die fest bleiben" title="Werte, die fest bleiben">` +
        `${_INFO_ICON}</button>`
      : '') +
    `</header>`
  );
}

function _shellHtml(cam) {
  const camId = cam.id;
  const frozen = frozenListHtml(camId);
  return (
    `<article class="netz-card" data-cam="${esc(camId)}">` +
    _headerHtml(cam, camId) +
    `<div class="netz-card-body"></div>` +
    (frozen
      ? `<div class="netz-frozen-box" id="netzFrozenBox-${esc(camId)}" hidden>` +
        `<b>Werte, die fest bleiben</b>${frozen}</div>`
      : '') +
    `</article>`
  );
}

// ── render ────────────────────────────────────────────────────────────

/** (Re)draw ONE camera's whole panel — header, and whichever sub-view is
 *  current (the net, or its Verlauf) — and rewire its interactions. Safe
 *  to call as the onRepaint of any interaction inside the panel: it only
 *  ever touches this one camera's slot. */
export function renderPanel(camId) {
  const slot = _slotFor(camId);
  const cam = (netzState.cameras || []).find((c) => c.id === camId);
  if (!slot || !cam) return;
  slot.innerHTML = _shellHtml(cam);
  const article = slot.querySelector('.netz-card');
  _bindHeader(article, camId);
  const body = article.querySelector('.netz-card-body');
  if (viewFor(camId) === 'verlauf') {
    _renderArchiveInto(body, camId);
  } else {
    body.innerHTML = tuneGroupLegendHtml() + netBodyHtml(cam);
    bindNetBody(article, () => renderPanel(camId));
    bindTuneDrag(body, () => renderPanel(camId));
  }
}

function _bindHeader(article, camId) {
  article.querySelector('[data-netz-toggle-verlauf]')?.addEventListener('click', () => {
    setView(camId, viewFor(camId) === 'verlauf' ? 'netz' : 'verlauf');
    renderPanel(camId);
  });
  // The frozen box flips its `hidden` attribute directly instead of going
  // through renderPanel — a repaint mid-drag drops the drag, and toggling
  // reference material has no reason to touch the net at all.
  article.querySelector('[data-netz-toggle-frozen]')?.addEventListener('click', () => {
    const box = byId(`netzFrozenBox-${camId}`);
    const btn = article.querySelector('[data-netz-toggle-frozen]');
    if (!box) return;
    const open = box.hasAttribute('hidden');
    box.toggleAttribute('hidden', !open);
    btn?.setAttribute('aria-expanded', String(open));
  });
}

// ── Verlauf sub-view ─────────────────────────────────────────────────────

async function _renderArchiveInto(body, camId) {
  if (archiveViewFor(camId) === 'detail' && netzState.detailByCam[camId]) {
    renderArchiveDetail(body, netzState.detailByCam[camId], {
      back: () => {
        setArchiveView(camId, 'list');
        renderPanel(camId);
      },
      afterRestore: (st) => {
        if (st && st.cam_id) netzState.states[st.cam_id] = st;
        setArchiveView(camId, 'list');
        renderPanel(camId);
      },
    });
    return;
  }
  const res = await fetchArchive({ cam: camId, ...archiveFilterFor(camId) });
  netzState.archiveByCam[camId] = res.ok ? res : { items: [] };
  // The panel may have re-rendered (or the operator may have switched back
  // to the net) while this fetch was in flight.
  if (viewFor(camId) !== 'verlauf' || !_slotFor(camId)?.contains(body)) return;
  renderArchiveList(body, netzState.archiveByCam[camId], camId, {
    reload: () => _renderArchiveInto(body, camId),
    openDetail: (eid) => _openArchiveDetail(camId, eid),
  });
}

async function _openArchiveDetail(camId, eid) {
  setArchiveView(camId, 'detail');
  netzState.detailIdByCam[camId] = eid;
  const res = await fetchArchiveRecord(eid);
  if (!res.ok || netzState.detailIdByCam[camId] !== eid) {
    showToast('Datensatz nicht gefunden.', 'warn');
    setArchiveView(camId, 'list');
    renderPanel(camId);
    return;
  }
  const row = (netzState.archiveByCam[camId]?.items || []).find((r) => r.event_id === eid);
  netzState.detailByCam[camId] = { ...res.record, badge: row?.badge || '⏳' };
  renderPanel(camId);
}

// ── mount / redraw ───────────────────────────────────────────────────────

/** Ensure every camera currently known to netzState has a rendered panel
 *  in its slot. Called after dashboard.js rebuilds #cameraCards — most
 *  slots already carry their PRESERVED panel DOM (dashboard.js reattaches
 *  them across its own re-renders), so this only fills slots that are
 *  genuinely empty: the first render, or a camera that just appeared. */
export function ensurePanelsMounted() {
  (netzState.cameras || []).forEach((cam) => {
    const slot = _slotFor(cam.id);
    if (slot && !slot.firstElementChild) renderPanel(cam.id);
  });
}

/** Re-draw every panel currently showing its net (not its Verlauf) — the
 *  viewBox mapping is uniform but the rendered px size is not, so a
 *  rotation or a window drag needs a repaint. Skipped entirely while a
 *  vertex is being dragged: rebuilding that panel's SVG mid-drag would
 *  drop the pointer capture (netz/_tune_drag.js's own resize comment). */
export function redrawOnResize() {
  if (isTuneDragging()) return;
  (netzState.cameras || []).forEach((cam) => {
    if (viewFor(cam.id) === 'netz' && _slotFor(cam.id)?.firstElementChild) renderPanel(cam.id);
  });
}

// ── page-level "Was zusammen wirkt" info button ──────────────────────────
// Cross-axis interaction notes are camera-independent reference text, so
// they get ONE header button for the whole Live-Feed section rather than
// being repeated on every panel (CLAUDE.md: no duplication).

export function initCombosInfo() {
  const btn = byId('netzCombosBtn');
  const box = byId('netzCombosBox');
  if (!btn || !box || box.dataset.wired) return;
  box.dataset.wired = '1';
  box.innerHTML = combosHtml();
  btn.addEventListener('click', () => {
    const open = box.hasAttribute('hidden');
    box.toggleAttribute('hidden', !open);
    btn.setAttribute('aria-expanded', String(open));
  });
}
