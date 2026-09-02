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
import {
  bindGhostToggle,
  bindNetBody,
  combosHtml,
  frozenSectionHtml,
  ghostToggleHtml,
  netBodyHtml,
  netProbeHtml,
} from './_cards.js';
import { svgGeometry } from './_tune_radar.js';
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

// ONE compact row: camera icon + name on the left, two icon-only buttons
// on the right — Verlauf and the ghost switch. The header and a separate
// controls row under the chart used to cost the net two rows of its own
// height beside a tile that never grows ("der Name … da kann eben oben
// eine Ecke sein … sonst nehmt's raus und macht das Netz einfach viel
// größer"). The history glyph once read as "Aktualisieren" and got a
// text label for it; the tooltip now carries that explanation instead,
// which is what keeps the row one button-height tall. No role badge
// (redundant with the camera's own identity), no per-panel frozen-values
// button (folded into the page-level "Was zusammen wirkt" box — see
// frozenSectionHtml in _cards.js).
const _HISTORY_ICON =
  `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" ` +
  `stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">` +
  `<path d="M3 12a9 9 0 1 0 3-6.7"/><polyline points="3 4 3 9 8 9"/>` +
  `<polyline points="12 7.5 12 12.5 15.5 14"/></svg>`;
const _VERLAUF_TITLE = 'Verlauf – frühere Profile dieser Kamera ansehen und wiederherstellen';
const _BACK_TITLE = 'Zurück zum Netz';

function _headerHtml(cam, camId) {
  const inVerlauf = viewFor(camId) === 'verlauf';
  const title = inVerlauf ? _BACK_TITLE : _VERLAUF_TITLE;
  return (
    `<header class="netz-card-hd">` +
    `<span class="netz-card-ic" style="color:${getCameraColor(cam)}" aria-hidden="true">` +
    `${getCameraIcon(cam.name || camId)}</span>` +
    `<h4>${esc(cam.name)}</h4>` +
    `<button type="button" class="netz-view-btn" data-netz-toggle-verlauf ` +
    `aria-pressed="${inVerlauf ? 'true' : 'false'}" aria-label="${title}" title="${title}">` +
    `${_HISTORY_ICON}</button>` +
    ghostToggleHtml(camId) +
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

// ── chart size ──────────────────────────────────────────────────────────
// The radar is drawn AT its box's px size (viewBox 1:1, see
// _tune_geometry.js), so the box has to be known BEFORE the body is
// rendered. .netz-card-chart is container-sized by CSS alone — flex-
// filled beside the tile on desktop, a fixed clamp() on a phone
// (32-netz.css) — never by the radar inside it, which is what makes an
// EMPTY box measure exactly what the drawn one will.

function _chartSizeOf(chart) {
  const r = chart.getBoundingClientRect();
  return r.width > 0 && r.height > 0 ? { width: r.width, height: r.height } : null;
}

/** Measure the box the net body is about to get, by laying out the real
 *  body MINUS the radar (netProbeHtml: empty chart plus the legend row
 *  that shares the panel's height with it). Null when the panel has no
 *  size yet (a hidden section) — the render then falls back to 560 x 300
 *  and the resize observer below repaints it the moment the box gets a
 *  size. */
function _measureChart(body) {
  body.innerHTML = netProbeHtml();
  return _chartSizeOf(body.querySelector('.netz-card-chart'));
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
    body.innerHTML = netBodyHtml(cam, _measureChart(body));
    bindNetBody(article, () => renderPanel(camId));
    bindTuneDrag(body, () => renderPanel(camId));
  }
  _observeSlot(slot);
}

function _bindHeader(article, camId) {
  article.querySelector('[data-netz-toggle-verlauf]')?.addEventListener('click', () => {
    setView(camId, viewFor(camId) === 'verlauf' ? 'netz' : 'verlauf');
    renderPanel(camId);
  });
  bindGhostToggle(article, () => renderPanel(camId));
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

/** Repaint ONE panel's net if its chart box no longer matches the size
 *  its radar was drawn at — a rotation, a window drag, the tile beside
 *  it changing height. Skipped while a vertex is being dragged:
 *  rebuilding that panel's SVG mid-drag would drop the pointer capture
 *  (netz/_tune_drag.js's own resize comment). The size check is what
 *  keeps this cheap on iOS, where every address-bar collapse fires a
 *  resize that changes nothing about the box. */
function _repaintIfResized(camId) {
  if (isTuneDragging() || viewFor(camId) !== 'netz') return;
  const chart = _slotFor(camId)?.querySelector('.netz-card-chart');
  const svg = chart?.querySelector('.netz-tune-svg');
  if (!svg) return;
  const size = _chartSizeOf(chart);
  if (!size) return;
  const geo = svgGeometry(svg);
  if (Math.abs(geo.w - size.width) < 1 && Math.abs(geo.h - size.height) < 1) return;
  renderPanel(camId);
}

/** Every panel currently showing its net — the window-resize path
 *  (netz/index.js). */
export function redrawOnResize() {
  (netzState.cameras || []).forEach((cam) => _repaintIfResized(cam.id));
}

// The slot resizes without any window event too: the desktop grid row
// takes its height from the Live-Feed tile (03-dashboard.css), so the
// tile loading, or the column changing width, changes the box under the
// radar. One observer for every slot; the callback only schedules — a
// repaint that changed the observed box from inside the callback would
// trip the browser's "loop completed with undelivered notifications"
// guard, and the debounce coalesces the burst a live drag of the window
// edge produces. Slots are preserved across dashboard.js re-renders, so
// observing the same node again is the no-op the spec makes it.
const _repaintTimers = new Map();

function _scheduleRepaint(camId) {
  clearTimeout(_repaintTimers.get(camId));
  _repaintTimers.set(
    camId,
    setTimeout(() => {
      _repaintTimers.delete(camId);
      _repaintIfResized(camId);
    }, 120),
  );
}

const _slotObserver =
  typeof ResizeObserver === 'function'
    ? new ResizeObserver((entries) => {
        entries.forEach((e) => _scheduleRepaint(e.target.dataset.camid));
      })
    : null;

function _observeSlot(slot) {
  _slotObserver?.observe(slot);
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
