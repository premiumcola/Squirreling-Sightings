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
import { bindNetBody, combosHtml, frozenSectionHtml, netBodyHtml } from './_cards.js';
import { tuneGroupLegendHtml } from './_tune_radar.js';
import { bindTuneDrag, isTuneDragging } from './_tune_drag.js';
import { renderArchiveDetail } from './_archive_detail.js';
import { renderArchiveList } from './_archive_list.js';
import {
  archiveFilterFor,
  archiveViewFor,
  netzState,
  setArchiveView,
  setView,
  viewFor,
} from './_state.js';

function _slotFor(camId) {
  return byId('cameraCards')?.querySelector(
    `.cam-net-slot[data-camid="${CSS.escape(camId)}"]`,
  );
}

// ── panel shell ─────────────────────────────────────────────────────────

// Camera icon + name, and one small text chip for the Verlauf toggle — no
// role badge (redundant with the camera's own identity), no icon-only
// button (the history glyph the toggle used to be read as "Aktualisieren"
// — a label removes the ambiguity outright instead of finding a clearer
// icon), no per-panel frozen-values button (folded into the page-level
// "Was zusammen wirkt" box instead — see frozenSectionHtml in _cards.js).
function _headerHtml(cam, camId) {
  const inVerlauf = viewFor(camId) === 'verlauf';
  return (
    `<header class="netz-card-hd">` +
    `<span class="netz-card-ic" style="color:${getCameraColor(cam)}" aria-hidden="true">` +
    `${getCameraIcon(cam.name || camId)}</span>` +
    `<h4>${esc(cam.name)}</h4>` +
    `<button type="button" class="netz-chip-toggle" data-netz-toggle-verlauf ` +
    `aria-pressed="${inVerlauf ? 'true' : 'false'}">${inVerlauf ? 'Zurück' : 'Verlauf'}</button>` +
    `</header>`
  );
}

function _shellHtml(cam) {
  const camId = cam.id;
  return (
    `<article class="netz-card" data-cam="${esc(camId)}">` +
    _headerHtml(cam, camId) +
    `<div class="netz-card-body"></div>` +
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
    // The group legend used to be prepended here, once per panel —
    // camera-independent reference text, so it now has ONE page-level
    // home (initGroupLegend below) instead of repeating on every panel.
    body.innerHTML = netBodyHtml(cam);
    bindNetBody(article, () => renderPanel(camId));
    bindTuneDrag(body, () => renderPanel(camId));
  }
}

function _bindHeader(article, camId) {
  article.querySelector('[data-netz-toggle-verlauf]')?.addEventListener('click', () => {
    setView(camId, viewFor(camId) === 'verlauf' ? 'netz' : 'verlauf');
    renderPanel(camId);
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

// ── page-level "Was zusammen wirkt" + "Werte, die fest bleiben" ─────────
// Both are camera-independent reference text (FROZEN_KEYS is one flat
// backend constant, identical for every camera), so they get ONE header
// button for the whole Live-Feed section rather than being repeated on
// every panel (CLAUDE.md: no duplication).

export function initCombosInfo() {
  const btn = byId('netzCombosBtn');
  const box = byId('netzCombosBox');
  if (!btn || !box || box.dataset.wired) return;
  box.dataset.wired = '1';
  box.innerHTML = combosHtml() + frozenSectionHtml();
  btn.addEventListener('click', () => {
    const open = box.hasAttribute('hidden');
    box.toggleAttribute('hidden', !open);
    btn.setAttribute('aria-expanded', String(open));
  });
}

// ── page-level group legend ──────────────────────────────────────────────
// tuneGroupLegendHtml() used to be prepended into every panel's body — the
// same colour key, byte-for-byte, on every one of N cards. One static
// render into a fixed slot under the section header instead.

export function initGroupLegend() {
  const box = byId('netzGroupLegend');
  if (!box || box.dataset.wired) return;
  box.dataset.wired = '1';
  box.innerHTML = tuneGroupLegendHtml();
}
