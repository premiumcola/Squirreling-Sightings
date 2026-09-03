// ─── weather/suntltest/_result.js ──────────────────────────────────────────
// The post-run card: cancelled / errored / the planned-vs-delivered diff
// grid with the QA-sidecar playback metrics.

import { byId, esc } from '../../core/dom.js';
import { rejectHintDe } from './_consts.js';

// G4 · "Was schief lief" one-sentence summary. Mentions the dominant
// rejection cluster + cache hits when any of those counts is non-zero.
// Returns '' when the run was clean.
function _whatWentWrong(d) {
  const rejected = d.rejected_by_reason || {};
  const sceneSkips = d.scene_skips_by_reason || {};
  const cached = parseInt(d.api_cached_grabs_total, 10) || 0;
  const bits = [];
  // Pick the dominant rejection reason if any.
  const rejEntries = Object.entries(rejected)
    .filter(([k, _v]) => !(k in sceneSkips)) // skip scene-classified
    .sort((a, b) => b[1] - a[1]);
  if (rejEntries.length) {
    const [head, count] = rejEntries[0];
    const hint = rejectHintDe(head) || 'siehe Log';
    bits.push(`${count} Frame(s) vom Decoder verworfen: <code>${esc(head)}</code> — ${esc(hint)}`);
  }
  const sceneTotal = Object.values(sceneSkips).reduce((a, b) => a + b, 0);
  if (sceneTotal > 0) {
    bits.push(`${sceneTotal} Slot(s) ohne Szeneninhalt übersprungen`);
  }
  if (cached > 0) {
    bits.push(
      `${cached} Slot(s) mit gecachtem Snapshot (Snapshot-API hat das gleiche Bild mehrfach geliefert)`,
    );
  }
  if (!bits.length) return '';
  return bits.join(' · ');
}

// G4 · quality-grade chip from the QA sidecar. green/yellow/red are
// the three buckets timelapse_qa.py emits. Colour tokens match the
// dashboard's existing severity chips.
function _qualityChip(grade) {
  if (!grade) return '';
  const map = {
    green: { lbl: 'GREEN', cls: 'suntltest-grade--green' },
    yellow: { lbl: 'YELLOW', cls: 'suntltest-grade--yellow' },
    red: { lbl: 'RED', cls: 'suntltest-grade--red' },
  };
  const m = map[grade] || { lbl: grade.toUpperCase(), cls: 'suntltest-grade--mute' };
  return `<span class="suntltest-grade ${m.cls}">${esc(m.lbl)}</span>`;
}

function _fmtNum(v, digits = 1) {
  if (v == null || !isFinite(v)) return '—';
  return Number(v).toFixed(digits);
}

function _card(cls, title, msg) {
  return `
      <div class="suntltest-result-card suntltest-result-card--${cls}">
        <div class="suntltest-result-title">${title}</div>
        <div class="suntltest-result-msg">${msg}</div>
      </div>`;
}

// G4 · planned vs delivered diff. Planned values come from the session
// (duration_s / target_duration_s / the fixed interval+fps); delivered
// values from stats + the QA sidecar when one was found.
function _diffGrid(d) {
  const windowMin = Math.round((parseInt(d.target_s, 10) || 0) / 60);
  const captureBudget = parseInt(d.expected_frames, 10) || 0;
  const plannedTarget = parseInt(d.target_duration_s, 10) || 0;
  const captured = parseInt(d.captured_frames, 10) || 0;
  const rejected = Math.max(0, captureBudget - captured);
  const cached = parseInt(d.api_cached_grabs_total, 10) || 0;
  const playback = d.qa && d.qa.playback ? d.qa.playback : null;
  const realisedDuration = playback ? Number(playback.duration_s) : null;
  const realisedFps = playback ? Number(playback.container_fps) : null;
  const uniqueFps = playback ? Number(playback.unique_fps) : null;
  // Right-column row helper: adds the ✓ when delivered matches planned.
  const okMark = (cond) =>
    cond ? ' <span class="suntltest-diff-mark suntltest-diff-mark--ok">✓</span>' : '';
  const fpsOk = realisedFps != null && Math.abs(realisedFps - 15) < 0.5;
  const intervalOk = true; // backend lock — always matches
  return `
      <div class="suntltest-diff">
        <div class="suntltest-diff-col">
          <div class="suntltest-diff-col-head">Geplant</div>
          <dl class="suntltest-diff-rows">
            <dt>Window</dt><dd>${windowMin} min</dd>
            <dt>Intervall</dt><dd>8 s</dd>
            <dt>Capture-Budget</dt><dd>${captureBudget} Frames</dd>
            <dt>Video-Länge</dt><dd>${plannedTarget} s</dd>
            <dt>Output-fps</dt><dd>15.0 fps</dd>
          </dl>
        </div>
        <div class="suntltest-diff-col">
          <div class="suntltest-diff-col-head">Geliefert</div>
          <dl class="suntltest-diff-rows">
            <dt>Window</dt><dd>${windowMin} min</dd>
            <dt>Intervall</dt><dd>8 s${okMark(intervalOk)}</dd>
            <dt>Captured</dt><dd>${captured}${rejected > 0 ? ` <span class="suntltest-diff-mute">(${rejected} verworfen)</span>` : ''}</dd>
            <dt>Video-Länge</dt><dd>${realisedDuration != null ? _fmtNum(realisedDuration, 2) + ' s' : '—'}</dd>
            <dt>Output-fps</dt><dd>${realisedFps != null ? _fmtNum(realisedFps, 2) + ' fps' : '—'}${okMark(fpsOk)}</dd>
            <dt>api_cached</dt><dd>${cached}${okMark(cached === 0)}</dd>
            <dt>unique_fps</dt><dd>${uniqueFps != null ? _fmtNum(uniqueFps, 1) : '—'}</dd>
            <dt>quality_grade</dt><dd>${_qualityChip(d.qa ? d.qa.quality_grade : null) || '—'}</dd>
          </dl>
        </div>
      </div>`;
}

export function renderResult(d) {
  const wrap = byId('suntltestResult');
  if (!wrap) return;
  if (!d || !d.finished) {
    wrap.hidden = true;
    wrap.innerHTML = '';
    return;
  }
  // Cancelled-state card — distinct from a generic error so the user
  // recognises this as their own action, not a failure. Rendered BEFORE
  // the generic error branch so a session that ends with both
  // ``cancelled=true`` AND ``error="abgebrochen"`` set still gets the
  // mute card, not the red one.
  if (d.cancelled) {
    wrap.hidden = false;
    wrap.innerHTML = _card(
      'mute',
      '⏹ Test abgebrochen',
      'Aufnahme wurde manuell abgebrochen — kein MP4 erzeugt.',
    );
    return;
  }
  if (d.error && !d.result_sighting_id) {
    wrap.hidden = false;
    wrap.innerHTML = _card('err', '⚠ Test ohne Ergebnis', esc(d.error));
    return;
  }
  if (!d.result_sighting_id) {
    wrap.hidden = true;
    return;
  }
  wrap.hidden = false;
  const id = d.result_sighting_id;
  const wrongLine = _whatWentWrong(d);
  const wrongBlock = wrongLine
    ? `<div class="suntltest-diff-wrong">Was schief lief: ${wrongLine}</div>`
    : '';
  wrap.innerHTML = `
    <div class="suntltest-result-card suntltest-result-card--ok">
      <div class="suntltest-result-title">🎬 Test-MP4 fertig</div>
      ${_diffGrid(d)}
      ${wrongBlock}
      <div class="suntltest-result-msg">Sichtungs-ID <code>${esc(id)}</code></div>
      <div class="suntltest-result-actions">
        <a class="btn-action accent" href="/api/weather/sightings/${encodeURIComponent(id)}/clip" target="_blank" rel="noopener">▶ MP4 öffnen</a>
        <button type="button" class="btn-action ghost" data-suntltest-jump="${esc(id)}">In Sichtungen anzeigen</button>
      </div>
    </div>`;
  wrap.querySelector('[data-suntltest-jump]')?.addEventListener('click', () => {
    // Best-effort — the Sichtungen panel reads its filter from the
    // URL hash on activation, so a hash bump is enough.
    window.location.hash = `#sichtungen?sighting=${encodeURIComponent(id)}`;
  });
}
