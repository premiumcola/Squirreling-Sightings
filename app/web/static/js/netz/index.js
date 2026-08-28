// ─── netz/index.js ─────────────────────────────────────────────────────────
// Erkennungsnetz — public API, hydration, tab router, window.* bridge.
//
// One page (#netz), two tabs: "Netz" and "Verlauf". Like storms/, both
// render into a single host and only one is in the DOM at a time, so the
// back button navigates for free and there is no modal-in-modal on iOS.
//
//   #netz                        → das Netz
//   #netz?tab=verlauf            → das Archiv
//   #netz?tab=verlauf&filter=offen  → the 07:00 release message's target

import { byId, esc } from '../core/dom.js';
import { showConfirm, showToast } from '../core/toast.js';
import { fetchArchive, fetchArchiveRecord, fetchState, resetAxis, setAuto } from './_api.js';
import { bindDrag, commitStaged, discardStaged } from './_drag.js';
import { MIN_RADAR_AXES, chartSide, legendHtml, renderBars, renderRadar } from './_radar.js';
import { renderArchiveDetail } from './_archive_detail.js';
import { renderArchiveList } from './_archive_list.js';
import { clearStaged, netzState, shownE, stagedCount } from './_state.js';
import { labelDe, pct } from './_helpers.js';

const HOST_ID = 'netzBody';

function _host() {
  return byId(HOST_ID);
}

// ── Netz-Tab ──────────────────────────────────────────────────────────

function _camChipsHtml(st) {
  const cams = st.cameras || [];
  if (cams.length < 2) return '';
  return (
    `<div class="netz-pills netz-cams">` +
    cams
      .map(
        (c) =>
          `<button type="button" class="netz-pill${
            c.id === st.cam_id ? ' is-active' : ''
          }" data-netz-cam="${esc(c.id)}">${esc(c.name)}</button>`,
      )
      .join('') +
    `</div>`
  );
}

// Day one: a regular polygon on the "Werk" ring, all grey and hollow.
// One progress line for the stratum closest to ready — no fake
// confidence, no spinner, no table of zeros.
function _progressHtml(st) {
  const p = st.progress;
  if (!p) return '';
  const cam = st.cam_name;
  return (
    `<div class="netz-progress">${esc(labelDe(p.label))} · ${esc(cam)}` +
    `<span>${p.judged} von ${p.needed} Rückmeldungen bis zur ersten automatischen ` +
    `Anpassung</span></div>`
  );
}

function _autoHtml(st) {
  return (
    `<label class="netz-auto"><span class="netz-auto-t">Automatik` +
    `<em>Aus = das Netz schlägt nur vor und ändert nichts.</em></span>` +
    `<input type="checkbox" class="switch-input" data-netz-auto${st.auto ? ' checked' : ''}>` +
    `<span class="switch"></span></label>`
  );
}

// A8 · naming the frozen values is the difference between "frozen" and
// "forgotten". Collapsed, one line each, no controls.
function _frozenHtml(st) {
  const rows = (st.frozen || [])
    .map((f) => `<li><code>${esc(f.key)}</code><span>${esc(f.de)}</span></li>`)
    .join('');
  return (
    `<details class="netz-frozen"><summary>Werte, die fest bleiben</summary>` +
    `<ul>${rows}</ul></details>`
  );
}

function _stagingHtml() {
  const n = stagedCount();
  if (!n) return '';
  return (
    `<div class="netz-stage" role="group" aria-label="Ungespeicherte Änderungen">` +
    `<span>${n} ${n === 1 ? 'Achse' : 'Achsen'} geändert</span>` +
    `<button type="button" class="netz-btn netz-btn--ghost" data-netz-discard>Verwerfen` +
    `</button>` +
    `<button type="button" class="netz-btn" data-netz-apply>Übernehmen</button></div>`
  );
}

function _chartHtml(st) {
  const axes = st.axes || [];
  if (!axes.length) {
    return (
      `<div class="netz-empty"><div class="netz-empty-title">Keine Klasse aktiv.</div>` +
      `<div class="netz-empty-sub">Wähle im Klassen-Filter der Kamera aus, worauf ` +
      `geachtet werden soll — jede aktive Klasse bekommt hier eine Achse.</div></div>`
    );
  }
  const values = axes.map((a) => shownE(a));
  const side = chartSide(Math.min(window.innerWidth || 375, 420));
  const chart =
    axes.length >= MIN_RADAR_AXES
      ? renderRadar({ axes, values, side, interactive: true })
      : renderBars({ axes, values, side, interactive: true });
  return `<div class="netz-chart">${chart}</div>${legendHtml(axes)}`;
}

function renderNet(host) {
  const st = netzState.state;
  if (!st) {
    host.innerHTML = `<div class="netz-empty"><div class="netz-empty-sub">Netz wird geladen …</div></div>`;
    return;
  }
  host.innerHTML =
    _camChipsHtml(st) +
    _chartHtml(st) +
    _progressHtml(st) +
    _autoHtml(st) +
    _frozenHtml(st) +
    _stagingHtml();
  bindDrag(host, () => renderNet(host));
  _bindNet(host);
}

function _bindNet(host) {
  host.querySelectorAll('[data-netz-cam]').forEach((b) =>
    b.addEventListener('click', async () => {
      if (stagedCount() && !(await showConfirm('Ungespeicherte Änderungen verwerfen?'))) return;
      clearStaged();
      netzState.camId = b.dataset.netzCam;
      await loadNet();
    }),
  );
  host.querySelector('[data-netz-apply]')?.addEventListener('click', () => {
    commitStaged(() => renderNet(host));
  });
  host.querySelector('[data-netz-discard]')?.addEventListener('click', () => {
    discardStaged(() => renderNet(host));
  });
  host.querySelector('[data-netz-auto]')?.addEventListener('change', async (e) => {
    const res = await setAuto(netzState.camId, e.target.checked);
    if (res.ok) netzState.state = res.state || netzState.state;
    renderNet(host);
  });
  host.querySelectorAll('[data-axis-label]').forEach((b) =>
    b.addEventListener('click', () => _openAxisSheet(host, b.dataset.axisLabel)),
  );
  // A vertex mid-drag repaints itself rather than re-rendering the SVG
  // under the finger, which would drop the pointer capture.
  host.addEventListener('netz:vertexmove', (ev) => _moveVertex(host, ev.detail));
}

function _moveVertex(host, { label, e }) {
  const st = netzState.state;
  const axes = st?.axes || [];
  const i = axes.findIndex((a) => a.label === label);
  if (i < 0) return;
  const values = axes.map((a, k) => (k === i ? e : shownE(a)));
  const side = chartSide(Math.min(window.innerWidth || 375, 420));
  const wrap = host.querySelector('.netz-chart');
  if (!wrap) return;
  wrap.innerHTML = renderRadar({ axes, values, side, interactive: true });
  bindDrag(host, () => renderNet(host));
}

// Counts, answer rate and blockers live HERE, not on the chart —
// "less text, more flat-design icons".
async function _openAxisSheet(host, label) {
  const axis = (netzState.state?.axes || []).find((a) => a.label === label);
  if (!axis) return;
  const ev = axis.evidence || {};
  const lines = [
    `Empfindlichkeit ${shownE(axis)} · ${
      { werk: 'Werk', manuell: 'manuell gesetzt', automatisch: 'automatisch' }[axis.provenance]
    }`,
    `Spuren ab ${pct(axis.spawn)} · Meldung ab ${pct(axis.push)} (${esc(
      axis.source?.push || '—',
    )})`,
    `Bestätigung ${axis.confirm_n}× in ${axis.confirm_s} s`,
    `${ev.judged || 0} beurteilt · ${ev.true || 0} richtig · ${ev.false || 0} falsch`,
    `Antwortquote ${Math.round((ev.answer_rate || 0) * 100)} %${
      ev.scope === 'pooled' ? ' · aus allen Kameras zusammengerechnet' : ''
    }`,
  ];
  if (ev.blockers?.length) lines.push(`Fehlt noch: ${ev.blockers.join(', ')}`);
  const proposal = Number.isFinite(Number(axis.proposal)) ? Number(axis.proposal) : null;
  const msg = `${labelDe(label)}\n${lines.join('\n')}${
    proposal !== null ? `\n\nVorschlag: ${proposal} — jetzt übernehmen?` : ''
  }`;
  if (proposal === null) {
    showToast(msg, 'info', { lifetime: 9000 });
    return;
  }
  if (await showConfirm(msg)) {
    netzState.staged[label] = proposal;
    netzState.snapshot[label] = axis.E;
    renderNet(host);
  }
}

export async function loadNet() {
  const host = _host();
  if (!host) return;
  netzState.loading = true;
  const res = await fetchState(netzState.camId);
  netzState.loading = false;
  if (res.ok) {
    netzState.state = res;
    netzState.camId = res.cam_id;
  }
  if (netzState.tab === 'netz') renderNet(host);
}

// ── Verlauf-Tab ───────────────────────────────────────────────────────

async function loadArchive() {
  const host = _host();
  if (!host) return;
  const res = await fetchArchive({ ...netzState.archiveFilter });
  netzState.archive = res.ok ? res : { items: [] };
  renderArchiveList(host, netzState.archive, {
    reload: loadArchive,
    openDetail: openArchiveDetail,
  });
}

async function openArchiveDetail(eid) {
  const host = _host();
  if (!host) return;
  netzState.archiveView = 'detail';
  netzState.detailId = eid;
  const res = await fetchArchiveRecord(eid);
  if (!res.ok || netzState.detailId !== eid) {
    showToast('Datensatz nicht gefunden.', 'warn');
    netzState.archiveView = 'list';
    return loadArchive();
  }
  const row = (netzState.archive?.items || []).find((r) => r.event_id === eid);
  netzState.detail = { ...res.record, badge: row?.badge || '⏳' };
  renderArchiveDetail(host, netzState.detail, {
    back: () => {
      netzState.archiveView = 'list';
      loadArchive();
    },
    afterRestore: (state) => {
      if (state) netzState.state = state;
      netzState.archiveView = 'list';
      loadArchive();
    },
  });
}

// ── tabs + routing ────────────────────────────────────────────────────

function _paintTabs() {
  const bar = byId('netzTabs');
  if (!bar) return;
  bar.querySelectorAll('[data-netz-tab]').forEach((b) => {
    b.classList.toggle('is-active', b.dataset.netzTab === netzState.tab);
    b.setAttribute('aria-selected', b.dataset.netzTab === netzState.tab ? 'true' : 'false');
  });
}

export function showTab(tab) {
  netzState.tab = tab === 'verlauf' ? 'verlauf' : 'netz';
  _paintTabs();
  if (netzState.tab === 'verlauf') {
    netzState.archiveView = 'list';
    loadArchive();
  } else {
    loadNet();
  }
}

function _routeFromHash() {
  const h = location.hash || '';
  if (!h.startsWith('#netz')) return;
  const q = h.includes('?') ? new URLSearchParams(h.slice(h.indexOf('?') + 1)) : null;
  if (q?.get('filter') === 'offen') netzState.archiveFilter.open = true;
  showTab(q?.get('tab') || 'netz');
}

let _observer = null;

/** Hydrate on first visibility, matching storms/. The panel is a section
 *  the operator scrolls into, not a background task. */
export function initNetz() {
  const sec = byId('netz');
  if (!sec || _observer) return;
  byId('netzTabs')
    ?.querySelectorAll('[data-netz-tab]')
    .forEach((b) => b.addEventListener('click', () => showTab(b.dataset.netzTab)));
  _observer = new IntersectionObserver(
    (entries) => {
      if (entries.some((e) => e.isIntersecting)) _routeFromHash();
    },
    { threshold: 0.02 },
  );
  _observer.observe(sec);
  if ((location.hash || '').startsWith('#netz')) _routeFromHash();
}

export async function resetWholeNet() {
  if (!(await showConfirm('Alle Achsen dieser Kamera auf Werk zurücksetzen?'))) return;
  const res = await resetAxis(netzState.camId, null);
  if (res.ok) {
    netzState.state = res.state || netzState.state;
    clearStaged();
    showToast('Netz auf Werkseinstellung.', 'success');
    renderNet(_host());
  }
}

window.addEventListener('hashchange', () => {
  if ((location.hash || '').startsWith('#netz')) _routeFromHash();
});

// Re-draw on resize so the square viewBox keeps its 1:1 mapping through
// a rotation or a window drag. Debounced; skipped mid-drag.
let _resizeTimer = null;
window.addEventListener(
  'resize',
  () => {
    if (!_host() || netzState.tab !== 'netz') return;
    if (_resizeTimer) clearTimeout(_resizeTimer);
    _resizeTimer = setTimeout(() => renderNet(_host()), 180);
  },
  { passive: true },
);

document.addEventListener('DOMContentLoaded', initNetz);

// window.* bridge — live-update.js's loadAll() reaches domain
// bootstrappers by global name, matching initStorms next door.
window.initNetz = initNetz;
window.netzResetAll = resetWholeNet;
