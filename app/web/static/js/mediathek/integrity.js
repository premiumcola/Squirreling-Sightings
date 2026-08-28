// ─── mediathek/integrity.js ────────────────────────────────────────────────
// "Integrität prüfen" — read-only report for GET /api/media/integrity.
//
// Renders INLINE inside the Mediathek-Wartung accordion rather than in a
// modal: the report is long, scrollable and read-only, and an inline
// block sidesteps the whole dvh / position:fixed / safe-area class of
// iOS bugs this repo keeps re-fixing.
//
// There is deliberately NO delete affordance anywhere in this file.
// Several finding categories (.raw-Clips, laufende Aufnahmen) are files
// that must not be removed, and a "alles bereinigen" button next to
// them would be the next data-loss incident.
import { byId, esc } from '../core/dom.js';
import { j } from '../core/api.js';
import { showToast } from '../core/toast.js';

const SEVERITY_LABEL = { warn: 'Prüfen', info: 'Hinweis' };

function _fmtMb(mb) {
  const n = Number(mb) || 0;
  if (n >= 1024) return (n / 1024).toFixed(1) + ' GB';
  return n.toFixed(1) + ' MB';
}

function _sizeRow(sizes) {
  const rows = [
    ['Aufnahmen', sizes.aufnahmen_mb],
    ['Timelapse', sizes.timelapse_mb],
    ['Timelapse-Einzelbilder', sizes.timelapse_frames_mb],
    ['Wetter', sizes.wetter_mb],
    ['Ad-hoc-Clips', sizes.adhoc_mb],
  ].filter(([, mb]) => (Number(mb) || 0) > 0);
  if (!rows.length) return '<div class="mi-empty">Keine Dateien auf der Platte.</div>';
  return `<div class="mi-sizes">${rows
    .map(
      ([label, mb]) =>
        `<span class="mi-size"><span class="mi-size-k">${esc(label)}</span><span class="mi-size-v">${esc(_fmtMb(mb))}</span></span>`,
    )
    .join('')}</div>`;
}

function _counterRow(z) {
  const drift = Number(z.abweichung) || 0;
  const driftChip =
    drift === 0
      ? '<span class="mi-chip mi-chip-ok">Zähler und Kacheln stimmen überein</span>'
      : `<span class="mi-chip mi-chip-warn">${drift > 0 ? drift : -drift} Timelapse-${
          drift > 0 ? 'Datei(en) ohne Eintrag' : 'Eintrag/Einträge ohne Datei'
        }</span>`;
  return `<div class="mi-counters">
      <span class="mi-chip">Ereignisse ${Number(z.ereignisse) || 0}</span>
      <span class="mi-chip">Timelapse ${Number(z.timelapse) || 0} von ${Number(z.timelapse_dateien) || 0} Datei(en)</span>
      ${driftChip}
    </div>`;
}

function _findingBlock(f) {
  const entries = (f.eintraege || [])
    .map(
      (e) =>
        `<li><code>${esc(e.pfad || '')}</code>${e.detail ? ` <span class="mi-detail">${esc(e.detail)}</span>` : ''}</li>`,
    )
    .join('');
  const more = f.gekuerzt
    ? `<li class="mi-detail">… ${f.anzahl - (f.eintraege || []).length} weitere nicht aufgelistet</li>`
    : '';
  const sev = f.schwere === 'info' ? 'info' : 'warn';
  return `<details class="mi-finding mi-sev-${sev}">
      <summary>
        <span class="mi-badge mi-badge-${sev}">${esc(SEVERITY_LABEL[sev] || sev)}</span>
        <span class="mi-finding-title">${esc(f.titel || f.code || '')}</span>
        <span class="mi-finding-count">${Number(f.anzahl) || 0}</span>
      </summary>
      <p class="mi-hint">${esc(f.hinweis || '')}</p>
      <ul class="mi-entries">${entries}${more}</ul>
    </details>`;
}

function _cameraBlock(cam) {
  const befunde = cam.befunde || [];
  const body = befunde.length
    ? befunde.map(_findingBlock).join('')
    : '<div class="mi-empty">Keine Auffälligkeiten.</div>';
  const archivTag = cam.aktiv
    ? ''
    : '<span class="mi-chip mi-chip-warn">Keiner aktiven Kamera zugeordnet</span>';
  return `<section class="mi-cam">
      <h4 class="mi-cam-name">${esc(cam.name || cam.camera_id)} ${archivTag}</h4>
      <div class="mi-cam-id"><code>${esc(cam.camera_id)}</code></div>
      ${_counterRow(cam.zaehler || {})}
      ${_sizeRow(cam.groessen || {})}
      ${body}
    </section>`;
}

function _foreignBlock(rows) {
  if (!rows.length) {
    return `<section class="mi-cam">
        <h4 class="mi-cam-name">Fremde Verzeichnisse</h4>
        <div class="mi-empty">Alle Medien auf der Platte gehören zu einer konfigurierten Kamera.</div>
      </section>`;
  }
  const items = rows
    .map(
      (r) =>
        `<li><code>${esc(r.camera_id)}</code> <span class="mi-detail">${esc(_fmtMb(r.groesse_mb))} · ${Number(r.dateien) || 0} Datei(en) · ${esc((r.verzeichnisse || []).join(', '))}</span></li>`,
    )
    .join('');
  return `<section class="mi-cam">
      <h4 class="mi-cam-name">Fremde Verzeichnisse <span class="mi-finding-count">${rows.length}</span></h4>
      <p class="mi-hint">Medien liegen unter einer Kamera-ID, die in den Einstellungen nicht (mehr) existiert — typisch nach einer Umbenennung oder einem IP-Wechsel. Nichts davon wird gelöscht; über „Zusammenführen“ in der Mediathek-Übersicht lassen sie sich einer aktiven Kamera zuordnen.</p>
      <ul class="mi-entries">${items}</ul>
    </section>`;
}

function _unsweptBlock(rows) {
  if (!rows.length) return '';
  const items = rows
    .map(
      (r) =>
        `<li><code>${esc(r.pfad)}</code> <span class="mi-detail">${esc(_fmtMb(r.groesse_mb))} · ${
          r.gefegt_von ? 'Bereinigung: ' + esc(r.gefegt_von) : 'wird nie automatisch bereinigt'
        }</span></li>`,
    )
    .join('');
  return `<section class="mi-cam">
      <h4 class="mi-cam-name">Speicher ausserhalb der Aufbewahrung</h4>
      <p class="mi-hint">Die Aufbewahrungsfrist gilt nur für <code>motion_detection/</code>. Diese Verzeichnisse wachsen unabhängig davon — bewusst, damit keine automatische Bereinigung die einzige Kopie einer Aufnahme entfernt.</p>
      <ul class="mi-entries">${items}</ul>
    </section>`;
}

function _render(report) {
  const box = byId('mediaIntegrityReport');
  if (!box) return;
  const cams = report.kameras || [];
  const total = cams.reduce((n, c) => n + (c.befunde || []).length, 0);
  const head = `<div class="mi-head">${cams.length} Kamera(s) geprüft · ${total} Befund(e) · nur Bericht, es wird nichts gelöscht</div>`;
  box.innerHTML =
    head +
    cams.map(_cameraBlock).join('') +
    _foreignBlock(report.fremde_verzeichnisse || []) +
    _unsweptBlock(report.ungefegte_verzeichnisse || []);
  box.hidden = false;
}

byId('mediaIntegrityBtn')?.addEventListener('click', async () => {
  const btn = byId('mediaIntegrityBtn');
  if (btn.disabled) return;
  btn.disabled = true;
  btn.classList.add('scanning');
  const box = byId('mediaIntegrityReport');
  if (box) {
    box.hidden = false;
    box.innerHTML = '<div class="mi-head">Archiv wird geprüft …</div>';
  }
  try {
    const report = await j('/api/media/integrity');
    if (!report?.ok) {
      showToast('Integritätsprüfung: ' + (report?.error || 'Fehler'), 'error');
      if (box) box.hidden = true;
      return;
    }
    _render(report);
  } catch (e) {
    showToast('Integritätsprüfung fehlgeschlagen: ' + (e.message || e), 'error');
    if (box) box.hidden = true;
  } finally {
    btn.disabled = false;
    btn.classList.remove('scanning');
  }
});
