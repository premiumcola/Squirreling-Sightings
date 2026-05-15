// ─── weather/settings-suntltest.js ─────────────────────────────────────────
// Sun-Timelapse TEST subtab. Fires an ad-hoc 60/120/300 s capture against
// the user-selected weather camera using the same backend code path the
// real sunrise/sunset schedule runs through, and surfaces every signal
// needed to diagnose why twilight captures come out monochrome with
// duplicate-frame stretches:
//
//   • daynight-override result (Color set / failed / skipped)
//   • elapsed / target seconds with a progress bar
//   • frame counters (captured / expected / retries / invalid)
//   • per-reason rejection breakdown — the smoking-gun for the
//     duplicate-frame bug (long blocks of frames rejected by
//     grey_uniform / too_dark / no_detail get padded by ffmpeg)
//   • scrolling tail of [sun-tl-test] / [weather] / [capture-stats]
//     log lines straight from the in-memory ring buffer the backend
//     keeps alongside the session
//
// Polls /api/weather/sun-tl/test/status every 2 s while a session is
// active; auto-stops on completion. Switching to another tab also
// stops the poller (settings.js calls stopSunTlTestPolling).

import { byId, esc } from "../core/dom.js";
import { state } from "../core/state.js";
import { showToast } from "../core/toast.js";

// G1 · System-wide capture-pipeline constants. Match
//   weather_service/_sun_tl.py (target_fps fixed at 15) and
//   settings/migrations.py (interval_s floor 8 s).
// The configurator below derives capture-budget + max video-length
// chips from these so an invalid (window, target) combination
// never makes it into the start payload.
const FPS = 15;
const INTERVAL_S = 8;

// Window options spanning smoke tests (5/10 min) through the
// production-equivalent 75 min lock. Internal seconds map below.
const _DURATIONS = [
  { s: 300,  label: "5 min" },
  { s: 600,  label: "10 min" },
  { s: 900,  label: "15 min" },
  { s: 1200, label: "20 min" },
  { s: 1800, label: "30 min" },
  { s: 2700, label: "45 min" },
  { s: 3600, label: "1 h" },
  { s: 4500, label: "75 min" },
];

// Final MP4 length picker — chips greyed out when the window doesn't
// produce enough frames for the chosen target × 15 fps.
const _TARGET_LENGTHS = [
  { s: 5,  label: "5 s" },
  { s: 10, label: "10 s" },
  { s: 15, label: "15 s" },
  { s: 20, label: "20 s" },
  { s: 30, label: "30 s" },
  { s: 37, label: "37 s" },
];

// Pure helpers — single source of truth for the math the backend
// will run. Keep these aligned with _sun_tl.py · _run_sun_capture
// _inner if either side ever changes.
function _captureBudget(windowS){
  return Math.floor(windowS / INTERVAL_S);
}
function _maxTargetS(windowS){
  return Math.floor(_captureBudget(windowS) / FPS);
}
function _isTargetValid(windowS, targetS){
  return targetS <= _maxTargetS(windowS);
}

// Local UI state — survives re-renders within a single tab visit.
let _selCam = null;
let _selPhase = "sunset";
let _selDuration = 1200;
let _selTargetLength = 10;
let _pollTimer = null;
let _lastEventTs = 0;
let _eventCache = [];

function _weatherCams(){
  return (state.cameras || []).filter(c => c && (c.weather && c.weather.enabled));
}

function _renderHeader(cams){
  const camOpts = cams.map(c =>
    `<option value="${esc(c.id)}"${c.id === _selCam ? ' selected' : ''}>${esc(c.name || c.id)}</option>`
  ).join('');
  const durChips = _DURATIONS.map(d =>
    `<button type="button" class="suntltest-chip${d.s === _selDuration ? ' is-active' : ''}" data-suntltest-dur="${d.s}">${d.label}</button>`
  ).join('');
  // G1 · target chips that exceed the capture budget for the current
  // window get the disabled state. Visual: opacity .35 + cursor not-
  // allowed. Click is blocked in the form binder below.
  const tgtChips = _TARGET_LENGTHS.map(d => {
    const valid = _isTargetValid(_selDuration, d.s);
    const cls = `suntltest-chip${d.s === _selTargetLength ? ' is-active' : ''}${valid ? '' : ' is-disabled'}`;
    return `<button type="button" class="${cls}" data-suntltest-tgt="${d.s}"${valid ? '' : ' aria-disabled="true"'}>${d.label}</button>`;
  }).join('');
  return `
    <div class="suntltest-form">
      <div class="suntltest-form-row">
        <label class="suntltest-lbl" for="suntltestCam">Kamera</label>
        <select id="suntltestCam" class="dark-select suntltest-sel">${camOpts}</select>
      </div>
      <div class="suntltest-form-row">
        <span class="suntltest-lbl">Phase</span>
        <div class="suntltest-phase-row" role="radiogroup" aria-label="Phase">
          <button type="button" class="suntltest-chip${_selPhase === 'sunrise' ? ' is-active' : ''}" data-suntltest-phase="sunrise">🌄 Sonnenaufgang</button>
          <button type="button" class="suntltest-chip${_selPhase === 'sunset'  ? ' is-active' : ''}" data-suntltest-phase="sunset">🌇 Sonnenuntergang</button>
        </div>
      </div>
      <div class="suntltest-form-row">
        <span class="suntltest-lbl">Aufnahme-Dauer</span>
        <div class="suntltest-dur-row" role="radiogroup" aria-label="Aufnahme-Dauer">${durChips}</div>
      </div>
      <div class="suntltest-form-row">
        <span class="suntltest-lbl">Video-Länge</span>
        <div class="suntltest-dur-row" id="suntltestTgtRow" role="radiogroup" aria-label="Video-Länge">${tgtChips}</div>
      </div>
      <div id="suntltestMath" class="suntltest-math">${_renderMathReadout(cams)}</div>
      <div class="suntltest-form-row suntltest-form-row--start">
        <button type="button" id="suntltestStart" class="btn-action accent suntltest-start">▶ Jetzt starten</button>
        <button type="button" id="suntltestCancel" class="btn-action danger suntltest-cancel" hidden>⏹ Abbrechen</button>
      </div>
      <div class="field-help suntltest-hint">Test fährt die echte Capture-Pipeline an (gleicher Code, kürzeres Fenster). Ergebnis landet als <code>_test_HHMMSS_…</code> in den Sichtungen.</div>
    </div>
    <div id="suntltestLive" class="suntltest-live" hidden></div>
    <div id="suntltestResult" class="suntltest-result" hidden></div>
  `;
}

// G1 · live math readout. Recomputed on every selector change. Shows
// the user EXACTLY what the backend will do with the chosen tuple so
// invalid combinations (target × 15 fps > budget) are obvious before
// the start. The check-/warn-icon at the bottom uses ✓ vs ⚠ to give
// a glanceable signal even when the user isn't reading the numbers.
function _renderMathReadout(cams){
  const cam = (cams || []).find(c => c.id === _selCam) || {};
  const camName = cam.name || _selCam || '—';
  const windowS = _selDuration;
  const windowLabel = (_DURATIONS.find(d => d.s === windowS) || {}).label || `${windowS} s`;
  const phaseLabel = _selPhase === 'sunrise' ? 'Sonnenaufgang' : 'Sonnenuntergang';
  const budget = _captureBudget(windowS);
  const targetS = _selTargetLength;
  const targetFrames = targetS * FPS;
  const effectiveRate = budget >= targetFrames
    ? FPS
    : (budget / Math.max(1, targetS));
  const valid = _isTargetValid(windowS, targetS);
  const rateStr = valid
    ? `<span class="suntltest-math-ok">${effectiveRate.toFixed(1)} fps ✓</span>`
    : `<span class="suntltest-math-warn">${effectiveRate.toFixed(1)} fps ⚠ (Capture-Budget reicht nicht für ${FPS} fps — wähle kürzeres Video oder längeres Window)</span>`;
  return `
    <div class="suntltest-math-head">► Du startest:</div>
    <dl class="suntltest-math-rows">
      <dt>Kamera</dt><dd>${esc(camName)}</dd>
      <dt>Phase</dt><dd>${phaseLabel}</dd>
      <dt>Window</dt><dd>${esc(windowLabel)} <span class="suntltest-math-mute">(${windowS} s)</span></dd>
      <dt>Intervall</dt><dd>${INTERVAL_S} s <span class="suntltest-math-mute">(fest)</span></dd>
      <dt>Capture-Budget</dt><dd>${budget} Frames</dd>
      <dt>Video-Länge</dt><dd>${targetS} s · ${FPS} fps = ${targetFrames} Frames</dd>
      <dt>echte Rate</dt><dd>${rateStr}</dd>
    </dl>`;
}

function _bindForm(root){
  byId('suntltestCam')?.addEventListener('change', (e) => {
    _selCam = e.target.value || null;
    _refreshConfigurator(root);
  });
  root.querySelectorAll('[data-suntltest-phase]').forEach(btn => {
    btn.addEventListener('click', () => {
      _selPhase = btn.dataset.suntltestPhase;
      root.querySelectorAll('[data-suntltest-phase]').forEach(b =>
        b.classList.toggle('is-active', b.dataset.suntltestPhase === _selPhase));
      _refreshConfigurator(root);
    });
  });
  root.querySelectorAll('[data-suntltest-dur]').forEach(btn => {
    btn.addEventListener('click', () => {
      _selDuration = parseInt(btn.dataset.suntltestDur, 10) || 1200;
      root.querySelectorAll('[data-suntltest-dur]').forEach(b =>
        b.classList.toggle('is-active', parseInt(b.dataset.suntltestDur, 10) === _selDuration));
      // G1 · when the window shrinks below the current target's
      // capture budget, snap the target down to the highest valid
      // chip so the user never lands on a disabled-chip selection.
      if (!_isTargetValid(_selDuration, _selTargetLength)){
        const maxTgt = _maxTargetS(_selDuration);
        const candidates = _TARGET_LENGTHS.filter(t => t.s <= maxTgt);
        _selTargetLength = candidates.length
          ? candidates[candidates.length - 1].s
          : _TARGET_LENGTHS[0].s;
      }
      _refreshConfigurator(root);
    });
  });
  root.querySelectorAll('[data-suntltest-tgt]').forEach(btn => {
    btn.addEventListener('click', () => {
      const next = parseInt(btn.dataset.suntltestTgt, 10) || 10;
      // Block clicks on disabled chips so the start payload can't
      // carry an over-budget target_duration_s. Visual feedback
      // already comes from the .is-disabled style.
      if (!_isTargetValid(_selDuration, next)) return;
      _selTargetLength = next;
      root.querySelectorAll('[data-suntltest-tgt]').forEach(b =>
        b.classList.toggle('is-active', parseInt(b.dataset.suntltestTgt, 10) === _selTargetLength));
      _refreshConfigurator(root);
    });
  });
  byId('suntltestStart')?.addEventListener('click', _startTest);
  byId('suntltestCancel')?.addEventListener('click', _cancelTest);
}

// G1 · re-render chip disabled-state + math readout + start-button
// enablement whenever a selector changes. Called from each handler
// above instead of a full _renderHeader so the user's focus / cursor
// position inside the form is preserved.
function _refreshConfigurator(root){
  const cams = _weatherCams();
  // Re-paint target chips (some may have flipped valid/invalid).
  const tgtRow = byId('suntltestTgtRow');
  if (tgtRow){
    tgtRow.innerHTML = _TARGET_LENGTHS.map(d => {
      const valid = _isTargetValid(_selDuration, d.s);
      const cls = `suntltest-chip${d.s === _selTargetLength ? ' is-active' : ''}${valid ? '' : ' is-disabled'}`;
      return `<button type="button" class="${cls}" data-suntltest-tgt="${d.s}"${valid ? '' : ' aria-disabled="true"'}>${d.label}</button>`;
    }).join('');
    // Re-bind the freshly-rendered chips.
    tgtRow.querySelectorAll('[data-suntltest-tgt]').forEach(btn => {
      btn.addEventListener('click', () => {
        const next = parseInt(btn.dataset.suntltestTgt, 10) || 10;
        if (!_isTargetValid(_selDuration, next)) return;
        _selTargetLength = next;
        _refreshConfigurator(root);
      });
    });
  }
  // Re-paint the math readout block.
  const mathHost = byId('suntltestMath');
  if (mathHost) mathHost.innerHTML = _renderMathReadout(cams);
  // Start button only enabled when the tuple is mathematically valid.
  const startBtn = byId('suntltestStart');
  if (startBtn) startBtn.disabled = !_isTargetValid(_selDuration, _selTargetLength) || !_selCam;
}

// Centralised UI toggle — hide the start button while a test is in
// flight so a fast clicker can't fire a second start before the
// poller has reset state. The cancel button mirrors the inverse.
function _setRunningUi(isRunning){
  const start = byId('suntltestStart');
  const cancel = byId('suntltestCancel');
  if (start)  { start.hidden = !!isRunning;  start.disabled = !!isRunning; }
  if (cancel) { cancel.hidden = !isRunning; cancel.disabled = false; }
}

async function _startTest(){
  // Synchronous reset BEFORE the network round-trip so the user
  // never sees the previous run's MP4 card or live tile while the
  // new run is starting. Polling will repaint these from the live
  // status response within ~1.5 s.
  const wrap = byId('suntltestResult');
  if (wrap) { wrap.hidden = true; wrap.innerHTML = ''; }
  const live = byId('suntltestLive');
  if (live) { live.hidden = true; live.innerHTML = ''; }
  // G3 · clear the per-slot cache so the previous session's cells
  // don't bleed into this run. _lastEventTs back to 0 so the first
  // poll re-fetches the whole event list.
  _resetEventCache();

  const btn = byId('suntltestStart');
  if (!_selCam) { showToast('Keine Wetter-Kamera ausgewählt.', 'error'); return; }
  if (btn) btn.disabled = true;
  try {
    const r = await fetch('/api/weather/sun-tl/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        cam_id: _selCam, phase: _selPhase,
        duration_s: _selDuration,
        target_duration_s: _selTargetLength,
      }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || !j.ok) {
      showToast('Start fehlgeschlagen: ' + (j.error || r.statusText || ('HTTP ' + r.status)), 'error');
      if (btn) btn.disabled = false;
      return;
    }
    showToast('Test läuft …', 'success');
    _setRunningUi(true);
    _startPolling();
  } catch (e) {
    showToast('Netzwerkfehler beim Start: ' + e, 'error');
    if (btn) btn.disabled = false;
  }
}

async function _cancelTest(){
  const btn = byId('suntltestCancel');
  if (btn) btn.disabled = true;
  try {
    const r = await fetch('/api/weather/sun-tl/test/cancel', { method: 'POST' });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || !j.ok) {
      showToast('Abbruch fehlgeschlagen: ' + (j.error || r.statusText), 'error');
      if (btn) btn.disabled = false;
      return;
    }
    showToast('Abbruch wird gesendet …', 'info');
    // Don't stop polling — let the status endpoint confirm the run
    // actually stopped, then _pollOnce will swap the UI back to the
    // start state and render the cancelled-state card.
  } catch (e) {
    showToast('Netzwerkfehler beim Abbruch: ' + e, 'error');
    if (btn) btn.disabled = false;
  }
}

// G3 · per-slot event cache. Keyed by slot index so the heatmap can
// render `expected_frames` cells where each cell looks up its event
// (if any) in O(1). _lastEventTs feeds the ?since=<float> query so
// the poll ships the delta only.
let _eventBySlot = new Map();

function _resetEventCache(){
  _eventBySlot = new Map();
  _lastEventTs = 0;
  _eventCache = [];
}

function _startPolling(){
  stopSunTlTestPolling();
  _pollOnce();
  // G3 · bumped 2 s → 1.5 s once the heatmap is live. With ?since=
  // delta polling the response stays small even on long sessions.
  _pollTimer = setInterval(_pollOnce, 1500);
}

export function stopSunTlTestPolling(){
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
}

async function _pollOnce(){
  let d = null;
  try {
    // G3 · ship the timestamp of the last event we've seen so the
    // backend's ?since=<float> filter returns only NEW slot_events.
    // The whole-history fallback is the unset default if _lastEventTs
    // is still 0 (fresh session).
    const url = _lastEventTs > 0
      ? `/api/weather/sun-tl/test/status?since=${encodeURIComponent(_lastEventTs)}`
      : `/api/weather/sun-tl/test/status`;
    const r = await fetch(url);
    d = await r.json();
  } catch (_err) {
    return;
  }
  // Merge any new slot_events into the per-slot cache. The status
  // payload's slot_events is ALWAYS the post-since delta, never the
  // whole list, so we accumulate forward.
  if (d && Array.isArray(d.slot_events)){
    for (const e of d.slot_events){
      if (!e || typeof e.slot !== 'number') continue;
      _eventBySlot.set(e.slot, e);
      if (e.ts > _lastEventTs) _lastEventTs = e.ts;
    }
  }
  _renderLive(d);
  if (d && (d.finished || !d.running)) {
    stopSunTlTestPolling();
    _setRunningUi(false);
    _renderResult(d);
  }
}

// G3 · density-style per-slot heatmap. One cell per expected slot,
// coloured by the resolved outcome from the slot_events ring buffer
// the backend ships (G2). Cell width is governed by CSS flex; on a
// 75-min × 8-s window (562 cells) iPhone width collapses cells to
// ~2 px each (purely density visual). Desktop wider cells get a
// title-tooltip with the per-slot detail. Cap at 800 cells —
// extreme runs beyond that bound aren't realistic for sun-tl.
function _renderHeatmap(d){
  const expected = Math.max(0, Math.min(800, parseInt(d.expected_frames, 10) || 0));
  if (expected === 0) return '';
  const cells = [];
  for (let i = 0; i < expected; i++){
    const ev = _eventBySlot.get(i);
    if (!ev){
      cells.push(`<div class="suntltest-cell" data-outcome="empty" data-slot="${i}"></div>`);
      continue;
    }
    const reason = ev.reason ? ` · ${ev.reason}` : '';
    const age = (typeof ev.age_ms === 'number') ? ` · ${ev.age_ms} ms` : '';
    const title = `Slot ${ev.slot} · ${ev.outcome}${reason}${age}`;
    cells.push(
      `<div class="suntltest-cell" data-outcome="${esc(ev.outcome)}" data-slot="${ev.slot}" title="${esc(title)}"></div>`,
    );
  }
  return `<div class="suntltest-heatmap" aria-label="Slot-Heatmap (${expected} Slots)">${cells.join('')}</div>`;
}

// G3 · counter chips coloured to match the heatmap legend. Each chip
// renders even when its count is 0 so the user can see the full set
// at a glance; counts are tabular-num so the row doesn't shift as
// values increment. Frame-age average is derived from the slot_events
// cache (age_ms field on fresh / cached / retry_ok outcomes).
function _renderCounterRow(d){
  const expected = parseInt(d.expected_frames, 10) || 0;
  const fresh = parseInt(d.fresh_captures, 10) || 0;
  const back  = parseInt(d.backfilled_slots, 10) || 0;
  const skip  = parseInt(d.skipped_slots, 10) || 0;
  const rej   = Math.max(0, (parseInt(d.invalid_frames, 10) || 0) - back - skip);
  const cached = parseInt(d.api_cached_grabs_total, 10) || 0;
  const currentSlot = Math.min(expected, _eventBySlot.size);
  // Average frame-age across the events we've seen that carry one.
  let ageSum = 0, ageCount = 0;
  for (const ev of _eventBySlot.values()){
    if (typeof ev.age_ms === 'number'){ ageSum += ev.age_ms; ageCount++; }
  }
  const ageStr = ageCount > 0 ? `${Math.round(ageSum / ageCount)} ms` : '—';
  const profileStr = d.validator_profile ? d.validator_profile : '—';
  return `
    <div class="suntltest-counter-row">
      <span class="suntltest-counter-progress">Slot <b>${currentSlot}</b> / ${expected}</span>
      <span class="suntltest-counter-chip" data-outcome="fresh">fresh ${fresh}</span>
      <span class="suntltest-counter-chip" data-outcome="cached">cached ${cached}</span>
      <span class="suntltest-counter-chip" data-outcome="rejected">rejected ${rej}</span>
      <span class="suntltest-counter-chip" data-outcome="backfilled">backfilled ${back}</span>
      <span class="suntltest-counter-chip" data-outcome="skipped">skipped ${skip}</span>
    </div>
    <div class="suntltest-counter-meta">
      <span>Frame-Alter ⌀ <b>${ageStr}</b></span>
      <span>Validator: <b>${esc(profileStr)}</b></span>
    </div>`;
}

// G3 · current-action row + ETA. During capture: "Slot N wird
// erfasst — ETA HH:MM (M min S s verbleiben)". Between capture-end
// and finished=true: "Encoding … (ffmpeg)". Hidden after finished
// (the result diff panel takes over).
function _renderActionRow(d){
  if (d.finished) return '';
  const elapsed = Math.max(0, parseInt(d.elapsed_s, 10) || 0);
  const target = Math.max(1, parseInt(d.target_s, 10) || 1);
  const expected = parseInt(d.expected_frames, 10) || 0;
  if (elapsed >= target){
    return `
      <div class="suntltest-action">
        <span class="suntltest-action-ico">▶</span>
        <span class="suntltest-action-text">Aktuell: <b>Encoding …</b> (ffmpeg)</span>
      </div>`;
  }
  const remaining = Math.max(0, target - elapsed);
  const remMin = Math.floor(remaining / 60);
  const remSec = remaining % 60;
  const remStr = remMin > 0 ? `${remMin} min ${remSec} s` : `${remSec} s`;
  const etaTs = new Date(Date.now() + remaining * 1000);
  const etaStr = etaTs.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const currentSlot = Math.min(expected, _eventBySlot.size + 1);
  return `
    <div class="suntltest-action">
      <span class="suntltest-action-ico">▶</span>
      <span class="suntltest-action-text">Aktuell: Slot <b>${currentSlot}</b> wird erfasst …</span>
      <span class="suntltest-action-eta">ETA <b>${esc(etaStr)}</b> · noch ${esc(remStr)}</span>
    </div>`;
}

function _renderLive(d){
  const wrap = byId('suntltestLive'); if (!wrap) return;
  if (!d || !d.cam_id) { wrap.hidden = true; wrap.innerHTML = ''; return; }
  wrap.hidden = false;
  // G3 · live view rebuilt around a per-slot heatmap. The old card-
  // in-card tile grid + per-reason reject list moves out (the
  // post-run diff panel surfaces the same data in a tighter form).
  // Row 1 heatmap, row 2 counter chips, row 3 action/ETA, row 4 log
  // tail — flat layout, no nested boxes.
  const phaseLabel = d.phase === 'sunrise' ? '🌄 Sonnenaufgang' : '🌇 Sonnenuntergang';
  const camName = (state.cameras || []).find(c => c.id === d.cam_id)?.name || d.cam_id;
  const stateClass = d.finished ? 'is-done' : (d.running ? 'is-running' : 'is-idle');
  // Profile + drift pills.
  const profileBadge = _profileBadge(d.validator_profile, d.baseline_brightness);
  const driftBadge   = _driftBadge(d.phase_drift_warning, d.phase_drift_min);
  const pillRow = (profileBadge || driftBadge)
    ? `<div class="suntltest-pill-row">${profileBadge}${driftBadge}</div>`
    : '';
  const logBlock = (d.last_log_lines || [])
    .slice(-60)
    .map(line => `<div class="suntltest-log-line">${esc(line)}</div>`)
    .join('');
  wrap.className = `suntltest-live ${stateClass}`;
  wrap.innerHTML = `
    <div class="suntltest-live-head">
      <div class="suntltest-live-title">${esc(camName)} · ${phaseLabel}</div>
      <div class="suntltest-live-status">${d.finished ? '✅ fertig' : (d.running ? '⏺ läuft' : '⏸ pausiert')}</div>
    </div>
    ${pillRow}
    ${_renderHeatmap(d)}
    ${_renderCounterRow(d)}
    ${_renderActionRow(d)}
    <div class="suntltest-section">
      <div class="suntltest-section-title">Log-Tail</div>
      <div class="suntltest-log-box" id="suntltestLog">${logBlock || '<div class="suntltest-log-line muted">— kein Log —</div>'}</div>
    </div>
    ${d.raw_dir ? `
    <div class="suntltest-section suntltest-rawdir">
      <span class="suntltest-rawdir-label">Roh-Frames:</span>
      <code class="suntltest-rawdir-path">${esc(d.raw_dir)}</code>
      <button type="button" class="suntltest-rawdir-copy" data-suntltest-copy="${esc(d.raw_dir)}" title="Pfad kopieren" aria-label="Pfad kopieren">⧉ kopieren</button>
    </div>` : ''}
  `;
  // Auto-stick the log to the bottom while it grows.
  const logBox = byId('suntltestLog');
  if (logBox) logBox.scrollTop = logBox.scrollHeight;
  // Wire the copy button. Falls back to a transient text-selection
  // when navigator.clipboard is unavailable (older Safari, http
  // contexts) so the path is still selectable manually.
  const copyBtn = wrap.querySelector('[data-suntltest-copy]');
  if (copyBtn){
    copyBtn.addEventListener('click', async () => {
      const path = copyBtn.getAttribute('data-suntltest-copy') || '';
      try {
        if (navigator.clipboard && navigator.clipboard.writeText){
          await navigator.clipboard.writeText(path);
        } else {
          const sel = window.getSelection();
          const range = document.createRange();
          range.selectNodeContents(wrap.querySelector('.suntltest-rawdir-path'));
          sel?.removeAllRanges(); sel?.addRange(range);
        }
        copyBtn.textContent = '✓ kopiert';
        setTimeout(() => { copyBtn.textContent = '⧉ kopieren'; }, 1500);
      } catch (_e){ /* noop — selection fallback already ran */ }
    });
  }
}

function _dnBadge(v){
  if (v === true)  return '<span class="suntltest-badge suntltest-badge--ok">Color gesetzt</span>';
  if (v === false) return '<span class="suntltest-badge suntltest-badge--err">fehlgeschlagen</span>';
  return '<span class="suntltest-badge suntltest-badge--mute">übersprungen</span>';
}

// Profile pill — DAY (sun yellow) / TWILIGHT (horizon orange) / NIGHT
// (deep blue). Soft tinted background, rounded ≥ 8 px, no thin border
// per project rules.
function _profileBadge(profile, brightness){
  if (!profile) return '';
  const labels = { day: 'DAY', twilight: 'TWILIGHT', night: 'NIGHT' };
  const cls = `suntltest-pill suntltest-pill--${profile}`;
  const lbl = labels[profile] || profile.toUpperCase();
  const sub = (typeof brightness === 'number')
    ? ` <span class="suntltest-pill-sub">brightness ${brightness}</span>`
    : '';
  return `<span class="${cls}">${esc(lbl)}${sub}</span>`;
}

// Drift pill — only renders when the backend flagged a drift > limit.
// Amber tint. Reads e.g. "Sunset-Capture lief 312 min nach Sonnen-
// untergang — Frames sind reine Nacht".
function _driftBadge(warning, _drift_min){
  if (!warning) return '';
  return `<span class="suntltest-pill suntltest-pill--drift">⚠ ${esc(warning)}</span>`;
}

// One-liner German hints under each rejected_by_reason row. Frontend
// strings only — backend stays language-agnostic.
const _REJECT_HINT_DE = {
  dead_area: 'Wenig Textur — wahrscheinlich Nachthimmel oder leere Wand',
  grey_midband: 'IR-Cut-Filter-Transition oder gleichmäßig grauer Himmel',
  grey_uniform: 'IR-Cut-Filter-Transition oder gleichmäßig grauer Himmel',
  no_detail: 'Frame fast komplett uniform — Encoder-Hickup oder Kamera-Reset',
  pink_artifact: 'H.265-Decode-Fehler — typisch bei schwacher Verbindung',
  patterned_magenta: 'H.265-Decode-Fehler — typisch bei schwacher Verbindung',
  colorbar: 'Kamera hat ein Test-Pattern gesendet',
  too_dark: 'Belichtung außerhalb des gültigen Bereichs',
  too_bright: 'Belichtung außerhalb des gültigen Bereichs',
  bottom_strip_white: 'H.265-Decoder hat unteren Bildbereich mit weißem Füllmuster ersetzt — RTSP-Paketverlust oder defekter Slice',
  bottom_strip_bright: 'Unterer Bildbereich deutlich heller als Szene — wahrscheinlich Macroblock-Korruption',
  horizontal_anomaly_band: 'Horizontales Korruptions-Band im Bild — H.265-Decoder-Fehler, Slice unvollständig oder Macroblock-Verlust',
  flat_gray_full_frame: 'Vollbild flach-grau — H.265-Decoder-Ausgabe ohne Szeneninhalt',
};
function _rejectHintDe(key){
  if (!key) return '';
  // Normalise the key:
  //   • strip everything from the first '(' so a parameterised
  //     reason head ("horizontal_anomaly_band(y=55%,h=2%,score=3.6)")
  //     matches the bare "horizontal_anomaly_band" entry
  //   • strip the _yNN_hNN band-location suffix that the test-mode
  //     reject sink appends to the folder name
  //   • collapse split_*_dead → "split" so the four split variants
  //     share one hint
  let bare = key;
  const lp = bare.indexOf('(');
  if (lp >= 0) bare = bare.slice(0, lp);
  bare = bare.replace(/_y\d+_h\d+$/, '');
  if (bare.startsWith('split_')) bare = 'split';
  return _REJECT_HINT_DE[bare] || _REJECT_HINT_DE[key] || '';
}

// G4 · "Was schief lief" one-sentence summary. Mentions the
// dominant rejection cluster + cache hits when any of those
// counts is non-zero. Returns '' when the run was clean.
function _whatWentWrong(d){
  const rejected = d.rejected_by_reason || {};
  const sceneSkips = d.scene_skips_by_reason || {};
  const cached = parseInt(d.api_cached_grabs_total, 10) || 0;
  const bits = [];
  // Pick the dominant rejection reason if any.
  const rejEntries = Object.entries(rejected)
    .filter(([k, _v]) => !(k in sceneSkips))   // skip scene-classified
    .sort((a, b) => b[1] - a[1]);
  if (rejEntries.length){
    const [head, count] = rejEntries[0];
    const hint = _rejectHintDe(head) || 'siehe Log';
    bits.push(`${count} Frame(s) vom Decoder verworfen: <code>${esc(head)}</code> — ${esc(hint)}`);
  }
  const sceneTotal = Object.values(sceneSkips).reduce((a, b) => a + b, 0);
  if (sceneTotal > 0){
    bits.push(`${sceneTotal} Slot(s) ohne Szeneninhalt übersprungen`);
  }
  if (cached > 0){
    bits.push(`${cached} Slot(s) mit gecachtem Snapshot (Snapshot-API hat das gleiche Bild mehrfach geliefert)`);
  }
  if (!bits.length) return '';
  return bits.join(' · ');
}

// G4 · quality-grade chip from the QA sidecar. green/yellow/red are
// the three buckets timelapse_qa.py emits. Colour tokens match the
// dashboard's existing severity chips.
function _qualityChip(grade){
  if (!grade) return '';
  const map = {
    green:  { lbl: 'GREEN',  cls: 'suntltest-grade--green' },
    yellow: { lbl: 'YELLOW', cls: 'suntltest-grade--yellow' },
    red:    { lbl: 'RED',    cls: 'suntltest-grade--red' },
  };
  const m = map[grade] || { lbl: grade.toUpperCase(), cls: 'suntltest-grade--mute' };
  return `<span class="suntltest-grade ${m.cls}">${esc(m.lbl)}</span>`;
}

function _fmtNum(v, digits = 1){
  if (v == null || !isFinite(v)) return '—';
  return Number(v).toFixed(digits);
}

function _renderResult(d){
  const wrap = byId('suntltestResult'); if (!wrap) return;
  if (!d || !d.finished) { wrap.hidden = true; wrap.innerHTML = ''; return; }
  // Cancelled-state card — distinct from a generic error so the user
  // recognises this as their own action, not a failure. Render BEFORE
  // the generic error branch so a session that ends with both
  // ``cancelled=true`` AND ``error="abgebrochen"`` set still gets the
  // mute card, not the red one.
  if (d.cancelled) {
    wrap.hidden = false;
    wrap.innerHTML = `
      <div class="suntltest-result-card suntltest-result-card--mute">
        <div class="suntltest-result-title">⏹ Test abgebrochen</div>
        <div class="suntltest-result-msg">Aufnahme wurde manuell abgebrochen — kein MP4 erzeugt.</div>
      </div>`;
    return;
  }
  if (d.error && !d.result_sighting_id) {
    wrap.hidden = false;
    wrap.innerHTML = `
      <div class="suntltest-result-card suntltest-result-card--err">
        <div class="suntltest-result-title">⚠ Test ohne Ergebnis</div>
        <div class="suntltest-result-msg">${esc(d.error)}</div>
      </div>`;
    return;
  }
  if (!d.result_sighting_id) { wrap.hidden = true; return; }
  wrap.hidden = false;
  // G4 · planned vs delivered diff. Pull planned values from the
  // session (duration_s / target_duration_s / fixed interval+fps);
  // delivered values from stats + the QA sidecar (when present).
  const id = d.result_sighting_id;
  const windowMin = Math.round((parseInt(d.target_s, 10) || 0) / 60);
  const captureBudget = parseInt(d.expected_frames, 10) || 0;
  const plannedTarget = parseInt(d.target_duration_s, 10) || 0;
  const captured = parseInt(d.captured_frames, 10) || 0;
  const rejected = Math.max(0, captureBudget - captured);
  const cached = parseInt(d.api_cached_grabs_total, 10) || 0;
  const qa = d.qa || null;
  const playback = qa && qa.playback ? qa.playback : null;
  const realisedDuration = playback ? Number(playback.duration_s) : null;
  const realisedFps = playback ? Number(playback.container_fps) : null;
  const uniqueFps = playback ? Number(playback.unique_fps) : null;
  const grade = qa ? qa.quality_grade : null;
  // Right-column row helper. cls=ok adds the ✓ when delivered matches
  // planned within tolerance; cls=warn flags a notable mismatch.
  const okMark = (cond) => cond ? ' <span class="suntltest-diff-mark suntltest-diff-mark--ok">✓</span>' : '';
  const fpsOk = realisedFps != null && Math.abs(realisedFps - 15) < 0.5;
  const intervalOk = true;     // backend lock — always matches
  const cachedOk = cached === 0;
  // Build the diff grid rows. PLANNED column on the left, DELIVERED on
  // the right; mobile (≤ 540 px) stacks them vertically via CSS.
  const wrongLine = _whatWentWrong(d);
  const wrongBlock = wrongLine
    ? `<div class="suntltest-diff-wrong">Was schief lief: ${wrongLine}</div>`
    : '';
  wrap.innerHTML = `
    <div class="suntltest-result-card suntltest-result-card--ok">
      <div class="suntltest-result-title">🎬 Test-MP4 fertig</div>
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
            <dt>api_cached</dt><dd>${cached}${okMark(cachedOk)}</dd>
            <dt>unique_fps</dt><dd>${uniqueFps != null ? _fmtNum(uniqueFps, 1) : '—'}</dd>
            <dt>quality_grade</dt><dd>${_qualityChip(grade) || '—'}</dd>
          </dl>
        </div>
      </div>
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

export function renderSunTlTestPanel(){
  const root = byId('sunTlTestPanel'); if (!root) return;
  const cams = _weatherCams();
  if (!cams.length) {
    root.innerHTML = `<div class="field-help">Keine Wetter-Kamera aktiv. Aktiviere eine Kamera unter "📷 Kameras".</div>`;
    return;
  }
  if (!cams.find(c => c.id === _selCam)) _selCam = cams[0].id;
  root.innerHTML = _renderHeader(cams);
  _bindForm(root);
  // G1 · initial start-button enabled-state + math readout sync.
  _refreshConfigurator(root);
  // Surface any prior session immediately on tab open so the user
  // doesn't lose state if they switch tabs mid-run.
  fetch('/api/weather/sun-tl/test/status').then(r => r.json()).then(d => {
    if (d && d.cam_id) {
      _renderLive(d);
      // Tab-open re-render: if a test is still in flight when the user
      // navigates back, surface the abort button immediately so they
      // can stop it without waiting for the next poll tick.
      _setRunningUi(d.running && !d.finished);
      if (d.running && !d.finished) _startPolling();
      else _renderResult(d);
    }
  }).catch(() => {});
}
