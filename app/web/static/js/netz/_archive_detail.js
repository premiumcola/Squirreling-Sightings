// ─── netz/_archive_detail.js ───────────────────────────────────────────────
// One record, full width: the frame, the verdict, the consequence
// paragraph unclamped, and a STATIC mini-radar of where every axis stood
// at that moment.
//
// The mini-radar is _radar.js with interactive:false — the same geometry
// the panel draws, so the archive cannot show a shape the editor would
// never produce.
//
// The bbox is NOT drawn here: `_best_frame_jpeg` burns it into the
// pixels before the archive re-encodes them, so the box is already in
// the image. Overlaying a second one would be a third copy of bbox math
// AND a doubled rectangle.

import { esc } from '../core/dom.js';
import { showConfirm, showToast } from '../core/toast.js';
import { archiveFrameUrl, restoreNet } from './_api.js';
import { MIN_RADAR_AXES, renderBars, renderRadar } from './_radar.js';
import { AXIS_ORDER } from './_mapping.js';
import { classChip, fmtDateTime, labelDe, pct, PROVENANCE_DE, verdictWord } from './_helpers.js';

const MINI_SIDE = 240;

function _axesFromState(netState) {
  const entries = Object.entries(netState || {});
  const order = new Map(AXIS_ORDER.map((l, i) => [l, i]));
  entries.sort((a, b) => (order.get(a[0]) ?? 99) - (order.get(b[0]) ?? 99));
  return entries.map(([label, info]) => ({
    label,
    E: Number(info.E) || 50,
    provenance: info.provenance || 'werk',
    evidence: info.evidence || { judged: 0, ready: false },
    proposal: null,
  }));
}

function _miniRadar(netState) {
  const axes = _axesFromState(netState);
  if (!axes.length) return '';
  const values = axes.map((a) => a.E);
  const svg =
    axes.length >= MIN_RADAR_AXES
      ? renderRadar({ axes, values, side: MINI_SIDE, interactive: false })
      : renderBars({ axes, values, side: MINI_SIDE, interactive: false });
  return `<div class="netz-mini">${svg}</div>`;
}

function _ladderRows(netState) {
  return Object.entries(netState || {})
    .map(
      ([label, i]) =>
        `<tr><td>${classChip(label)}</td><td>${esc(String(i.E))}</td>` +
        `<td>${esc(pct(i.spawn))}</td><td>${esc(pct(i.push))}</td>` +
        `<td class="netz-src">${esc(i.source?.push || '—')}</td>` +
        `<td class="netz-src">${esc(PROVENANCE_DE[i.provenance] || i.provenance || '')}</td>` +
        `</tr>`,
    )
    .join('');
}

function _frameHtml(rec) {
  if (rec.kind === 'netz_aenderung') return '';
  return (
    `<img class="netz-det-frame" alt="" src="${esc(archiveFrameUrl(rec.event_id))}" ` +
    `onerror="this.closest('.netz-det-figure')?.remove()">`
  );
}

export function renderArchiveDetail(host, rec, handlers) {
  const det = rec.detection || {};
  const cons = rec.consequence || {};
  const verdict = rec.verdict || {};
  const score = Number.isFinite(Number(det.score))
    ? ` · ${Math.round(Number(det.score) * 100)} %`
    : '';
  host.innerHTML =
    `<div class="netz-det">` +
    `<button type="button" class="netz-back" data-arc-back>← Verlauf</button>` +
    `<div class="netz-det-head">${classChip(det.label)}` +
    `<span class="netz-arc-cam">${esc(rec.cam_name || '')}</span>` +
    `<span class="netz-arc-time">${esc(fmtDateTime(rec.ts))}${esc(score)}</span></div>` +
    (rec.kind === 'netz_aenderung'
      ? ''
      : `<figure class="netz-det-figure">${_frameHtml(rec)}</figure>`) +
    `<div class="netz-det-verdict"><span class="netz-badge" data-state="${esc(
      cons.state || 'pending',
    )}">${esc(rec.badge || '')}</span>` +
    `${esc(verdictWord({ verdict: verdict.value, corrected_label: verdict.corrected_label }))}` +
    `</div>` +
    `<p class="netz-det-reason">${cons.reason_de || ''}</p>` +
    `<div class="netz-det-sub">Netz zu diesem Zeitpunkt</div>` +
    _miniRadar(rec.net_state) +
    `<div class="netz-table-wrap"><table class="netz-table">` +
    `<thead><tr><th>Klasse</th><th>E</th><th>Spawn</th><th>Meldung</th>` +
    `<th>Ebene</th><th>Quelle</th></tr></thead>` +
    `<tbody>${_ladderRows(rec.net_state)}</tbody></table></div>` +
    `<button type="button" class="netz-btn netz-btn--ghost" data-arc-restore>` +
    `Netz zu diesem Zeitpunkt wiederherstellen</button>` +
    `</div>`;
  host.querySelector('[data-arc-back]')?.addEventListener('click', handlers.back);
  host
    .querySelector('[data-arc-restore]')
    ?.addEventListener('click', () => _restore(rec, handlers));
}

async function _restore(rec, handlers) {
  const when = fmtDateTime(rec.ts);
  const ok = await showConfirm(
    `Alle Achsen von ${rec.cam_name} auf den Stand vom ${when} zurücksetzen? ` +
      `Die Achsen gelten danach als manuell gesetzt.`,
  );
  if (!ok) return;
  const res = await restoreNet(rec.event_id);
  if (!res.ok) {
    showToast('Wiederherstellen fehlgeschlagen.', 'error');
    return;
  }
  const n = Object.keys(res.written || {}).length;
  showToast(`${n} ${n === 1 ? 'Achse' : 'Achsen'} wiederhergestellt.`, 'success');
  handlers.afterRestore(res.state);
}

export function detailLabel(rec) {
  return labelDe((rec.detection || {}).label);
}
