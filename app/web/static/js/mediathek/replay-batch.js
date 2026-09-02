// ─── mediathek/replay-batch.js ─────────────────────────────────────────────
// "Vogel-Nachanalyse" — replays every archived bird clip against today's
// settings and shows the aggregate.
//
// POST /api/replay/batch starts the run, GET /api/replay/batch polls it,
// POST /api/replay/batch/cancel stops it at the next clip boundary. The
// run is minutes to hours, so nothing here holds a request open; the
// same start/poll shape integrity.js uses next door, with a cancel.
//
// Renders INLINE into the maintenance panel and reuses the .mi-* report
// classes integrity.js already styles — one report look, and no modal,
// which keeps this clear of the dvh / position:fixed / safe-area bugs
// this repo keeps re-fixing on iOS.
//
// On the two "more birds" numbers: the strict one compares whole clip
// against whole clip and is the honest headline. The loose one includes
// clips whose only baseline was the single frame the event froze at
// recording start, where finding more is expected. Both are shown, the
// strict one first, because a batch that flatters itself is worse than
// no batch.
import { byId, esc } from '../core/dom.js';
import { apiGet, apiPost } from '../core/api.js';
import { showToast } from '../core/toast.js';

const POLL_MS = 2000;

const PHASE_TEXT = {
  zaehlen: 'Clips werden gezählt …',
  laeuft: 'läuft',
  fertig: 'fertig',
  abgebrochen: 'abgebrochen',
  fehler: 'fehlgeschlagen',
};

let timer = null;

function _chip(label, value, tone) {
  const cls = tone ? ` mi-chip-${tone}` : '';
  return `<span class="mi-chip${cls}">${esc(label)} ${esc(String(value))}</span>`;
}

function _moverRow(m) {
  const dir = m.delta >= 0 ? '+' : '';
  const tone = m.delta >= 0 ? 'ok' : 'warn';
  return `<li>
      <code>${esc(m.event_id)}</code>
      <span class="mi-detail">${esc(m.label)} · ${m.before.toFixed(2)} → ${m.after.toFixed(2)}
        <span class="rb-delta rb-delta-${tone}">${dir}${m.delta.toFixed(2)}</span></span>
    </li>`;
}

function _movers(report) {
  const rows = report.movers || [];
  if (!rows.length) return '';
  return `<section class="mi-cam">
      <h4 class="mi-cam-name">Grösste Vertrauens-Sprünge</h4>
      <p class="mi-hint">Wie sich die Erkennungs-Sicherheit derselben Box verschoben hat.</p>
      <ul class="mi-entries">${rows.map(_moverRow).join('')}</ul>
    </section>`;
}

function _headline(report) {
  const strict = Number(report.birds_gained_strict) || 0;
  const loose = Number(report.birds_gained_events) || 0;
  const extra = loose > strict ? ` (${loose} inkl. Clips ohne Track-Vergleich)` : '';
  return `<section class="mi-cam">
      <h4 class="mi-cam-name">Zusätzliche Vögel</h4>
      <p class="mi-hint">Clips, in denen die heutige Erkennung MEHR Vögel findet als bisher
        gespeichert${esc(extra)}. Verglichen wird ganzer Clip gegen ganzen Clip; wo dafür kein
        früherer Track vorlag, steht der Vergleich nur gegen das eine Bild vom Aufnahmestart.</p>
      <div class="mi-counters">
        ${_chip('Mehr Vögel', strict, strict ? 'ok' : null)}
        ${_chip('Weniger Vögel', Number(report.birds_lost_events) || 0, report.birds_lost_events ? 'warn' : null)}
        ${_chip('Track-Vergleich möglich', Number(report.tracks_comparable_events) || 0)}
      </div>
    </section>`;
}

function _species(report) {
  const n = Number(report.species_nameable_events) || 0;
  return `<section class="mi-cam">
      <h4 class="mi-cam-name">Noch ohne Artnamen</h4>
      <p class="mi-hint">Die Nachanalyse bestimmt selbst KEINE Arten — sie erkennt nur Vögel.
        Diese Clips zeigen Vögel, tragen aber keinen Artnamen; „Vogelarten nachträglich
        bestimmen“ kann ihnen jetzt einen geben.</p>
      <div class="mi-counters">${_chip('Clips', n, n ? 'warn' : 'ok')}</div>
    </section>`;
}

function _overview(report) {
  return `<div class="mi-counters">
      ${_chip('Geprüft', Number(report.examined) || 0)}
      ${_chip('Verändert', Number(report.changed) || 0, report.changed ? 'warn' : 'ok')}
      ${_chip('Unverändert', Number(report.unchanged) || 0)}
      ${_chip('Alarm anders', Number(report.alert_changed_events) || 0)}
      ${_chip('Etwas verloren', Number(report.lost_events) || 0, report.lost_events ? 'warn' : null)}
      ${report.errors ? _chip('Fehler', report.errors, 'warn') : ''}
    </div>`;
}

function _renderReport(report) {
  const box = byId('replayBatchReport');
  if (!box) return;
  if (!report) {
    box.hidden = true;
    return;
  }
  const when = report.generated_at ? ` · ${esc(report.generated_at)}` : '';
  const partial = report.cancelled ? ' · abgebrochen, Teilergebnis' : '';
  box.innerHTML =
    `<div class="mi-head">${Number(report.examined) || 0} von ${Number(report.selected) || 0} Vogel-Clips${esc(partial)}${when}</div>` +
    _overview(report) +
    _headline(report) +
    _species(report) +
    _movers(report);
  box.hidden = false;
}

function _renderStatus(state) {
  const line = byId('replayBatchStatus');
  if (!line) return;
  if (!state.running && !state.phase) {
    line.hidden = true;
    return;
  }
  const phase = PHASE_TEXT[state.phase] || state.phase || '';
  const total = Number(state.total) || 0;
  const done = Number(state.done) || 0;
  const pct = total ? Math.round((done / total) * 100) : 0;
  const bar = state.running
    ? `<span class="rb-bar"><span class="rb-bar-fill" style="width:${pct}%"></span></span>`
    : '';
  const counts = total ? `${done} / ${total}` : '…';
  const errs = state.errors ? ` · ${state.errors} Fehler` : '';
  line.innerHTML = `<span class="rb-phase">${esc(phase)}</span> <span class="rb-counts">${esc(counts)}${esc(errs)}</span>${bar}`;
  line.hidden = false;
}

function _setRunning(running) {
  const start = byId('replayBatchBtn');
  const cancel = byId('replayBatchCancelBtn');
  if (start) {
    start.disabled = running;
    start.classList.toggle('scanning', running);
  }
  if (cancel) cancel.hidden = !running;
}

async function _tick() {
  const state = await apiGet('/api/replay/batch');
  if (!state) return;
  _renderStatus(state);
  _setRunning(!!state.running);
  if (state.running) return;
  _stopPolling();
  if (state.error) showToast('Nachanalyse fehlgeschlagen: ' + state.error, 'error');
  _renderReport(state.report);
}

function _stopPolling() {
  if (timer !== null) {
    clearInterval(timer);
    timer = null;
  }
}

function _startPolling() {
  _stopPolling();
  timer = setInterval(() => {
    _tick().catch((e) => {
      _stopPolling();
      _setRunning(false);
      showToast('Nachanalyse: Status nicht lesbar — ' + (e.message || e), 'error');
    });
  }, POLL_MS);
}

byId('replayBatchBtn')?.addEventListener('click', async () => {
  _setRunning(true);
  try {
    const started = await apiPost('/api/replay/batch', {});
    if (started?.already_running) showToast('Ein Durchlauf läuft bereits.', 'info');
    _renderStatus(started || { running: true, phase: 'zaehlen' });
    _startPolling();
  } catch (e) {
    _setRunning(false);
    showToast('Nachanalyse konnte nicht starten: ' + (e.message || e), 'error');
  }
});

byId('replayBatchCancelBtn')?.addEventListener('click', async () => {
  const btn = byId('replayBatchCancelBtn');
  if (btn) btn.disabled = true;
  try {
    await apiPost('/api/replay/batch/cancel', {});
    showToast('Abbruch angefordert — der laufende Clip wird noch beendet.', 'info');
  } catch (e) {
    showToast('Abbruch fehlgeschlagen: ' + (e.message || e), 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
});

// A run started before this page load is still going; a report from a
// previous run outlives a restart. Both are answered by one status read,
// so the panel is never blank about work that already happened.
apiGet('/api/replay/batch')
  .then((state) => {
    if (!state) return;
    _renderStatus(state);
    _setRunning(!!state.running);
    if (state.running) _startPolling();
    else _renderReport(state.report);
  })
  .catch(() => {});
