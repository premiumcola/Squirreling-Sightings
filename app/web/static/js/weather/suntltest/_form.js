// ─── weather/suntltest/_form.js ────────────────────────────────────────────
// The configurator: camera / phase / window / video-length pickers, the
// live math readout, and the running-vs-idle button swap.
//
// Knows nothing about starting or polling a test — `bindForm` takes the
// start/cancel handlers as arguments. That injection is what keeps this
// module and _run.js from importing each other.

import { byId, esc } from '../../core/dom.js';
import { state } from '../../core/state.js';
import {
  DURATIONS,
  FPS,
  INTERVAL_S,
  TARGET_LENGTHS,
  captureBudget,
  isTargetValid,
  maxTargetS,
} from './_consts.js';
import { S } from './_state.js';

export function weatherCams() {
  return (state.cameras || []).filter((c) => c && c.weather && c.weather.enabled);
}

// G1 · target chips that exceed the capture budget for the current
// window get the disabled state. Visual: opacity .35 + cursor not-
// allowed. Click is blocked in the binder below. Built here once —
// the initial render and every _refreshConfigurator repaint used to
// carry their own copy of this template and could drift apart.
function _targetChipsHtml() {
  return TARGET_LENGTHS.map((d) => {
    const valid = isTargetValid(S.duration, d.s);
    const cls = `suntltest-chip${d.s === S.targetLength ? ' is-active' : ''}${valid ? '' : ' is-disabled'}`;
    return `<button type="button" class="${cls}" data-suntltest-tgt="${d.s}"${valid ? '' : ' aria-disabled="true"'}>${d.label}</button>`;
  }).join('');
}

// Also one implementation, for the same reason. _refreshConfigurator
// rebuilds the whole row, so the chips it paints need re-binding and
// the `is-active` toggling the old inline handler did was overwritten
// by that rebuild anyway.
function _bindTargetChips(root) {
  root.querySelectorAll('[data-suntltest-tgt]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const next = parseInt(btn.dataset.suntltestTgt, 10) || 10;
      // Block clicks on disabled chips so the start payload can't
      // carry an over-budget target_duration_s. Visual feedback
      // already comes from the .is-disabled style.
      if (!isTargetValid(S.duration, next)) return;
      S.targetLength = next;
      refreshConfigurator();
    });
  });
}

export function renderHeader(cams) {
  const camOpts = cams
    .map(
      (c) =>
        `<option value="${esc(c.id)}"${c.id === S.cam ? ' selected' : ''}>${esc(c.name || c.id)}</option>`,
    )
    .join('');
  const durChips = DURATIONS.map(
    (d) =>
      `<button type="button" class="suntltest-chip${d.s === S.duration ? ' is-active' : ''}" data-suntltest-dur="${d.s}">${d.label}</button>`,
  ).join('');
  return `
    <div class="suntltest-form">
      <div class="suntltest-form-row">
        <label class="suntltest-lbl" for="suntltestCam">Kamera</label>
        <select id="suntltestCam" class="dark-select suntltest-sel">${camOpts}</select>
      </div>
      <div class="suntltest-form-row">
        <span class="suntltest-lbl">Phase</span>
        <div class="suntltest-phase-row" role="radiogroup" aria-label="Phase">
          <button type="button" class="suntltest-chip${S.phase === 'sunrise' ? ' is-active' : ''}" data-suntltest-phase="sunrise">🌄 Sonnenaufgang</button>
          <button type="button" class="suntltest-chip${S.phase === 'sunset' ? ' is-active' : ''}" data-suntltest-phase="sunset">🌇 Sonnenuntergang</button>
        </div>
      </div>
      <div class="suntltest-form-row">
        <span class="suntltest-lbl">Aufnahme-Dauer</span>
        <div class="suntltest-dur-row" role="radiogroup" aria-label="Aufnahme-Dauer">${durChips}</div>
      </div>
      <div class="suntltest-form-row">
        <span class="suntltest-lbl">Video-Länge</span>
        <div class="suntltest-dur-row" id="suntltestTgtRow" role="radiogroup" aria-label="Video-Länge">${_targetChipsHtml()}</div>
      </div>
      <div id="suntltestMath" class="suntltest-math">${renderMathReadout(cams)}</div>
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
export function renderMathReadout(cams) {
  const cam = (cams || []).find((c) => c.id === S.cam) || {};
  const camName = cam.name || S.cam || '—';
  const windowS = S.duration;
  const windowLabel = (DURATIONS.find((d) => d.s === windowS) || {}).label || `${windowS} s`;
  const phaseLabel = S.phase === 'sunrise' ? 'Sonnenaufgang' : 'Sonnenuntergang';
  const budget = captureBudget(windowS);
  const targetS = S.targetLength;
  const targetFrames = targetS * FPS;
  const effectiveRate = budget >= targetFrames ? FPS : budget / Math.max(1, targetS);
  const valid = isTargetValid(windowS, targetS);
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

// G1 · when the window shrinks below the current target's capture
// budget, snap the target down to the highest valid chip so the user
// never lands on a disabled-chip selection.
function _snapTargetIntoBudget() {
  if (isTargetValid(S.duration, S.targetLength)) return;
  const candidates = TARGET_LENGTHS.filter((t) => t.s <= maxTargetS(S.duration));
  S.targetLength = candidates.length ? candidates[candidates.length - 1].s : TARGET_LENGTHS[0].s;
}

function _bindPhaseAndDuration(root) {
  root.querySelectorAll('[data-suntltest-phase]').forEach((btn) => {
    btn.addEventListener('click', () => {
      S.phase = btn.dataset.suntltestPhase;
      root
        .querySelectorAll('[data-suntltest-phase]')
        .forEach((b) => b.classList.toggle('is-active', b.dataset.suntltestPhase === S.phase));
      refreshConfigurator();
    });
  });
  root.querySelectorAll('[data-suntltest-dur]').forEach((btn) => {
    btn.addEventListener('click', () => {
      S.duration = parseInt(btn.dataset.suntltestDur, 10) || 1200;
      root
        .querySelectorAll('[data-suntltest-dur]')
        .forEach((b) =>
          b.classList.toggle('is-active', parseInt(b.dataset.suntltestDur, 10) === S.duration),
        );
      _snapTargetIntoBudget();
      refreshConfigurator();
    });
  });
}

export function bindForm(root, { onStart, onCancel }) {
  byId('suntltestCam')?.addEventListener('change', (e) => {
    S.cam = e.target.value || null;
    refreshConfigurator();
  });
  _bindPhaseAndDuration(root);
  _bindTargetChips(root);
  byId('suntltestStart')?.addEventListener('click', onStart);
  byId('suntltestCancel')?.addEventListener('click', onCancel);
}

// G1 · re-render chip disabled-state + math readout + start-button
// enablement whenever a selector changes. Called from each handler
// above instead of a full renderHeader so the user's focus / cursor
// position inside the form is preserved.
export function refreshConfigurator() {
  // Re-paint target chips (some may have flipped valid/invalid).
  const tgtRow = byId('suntltestTgtRow');
  if (tgtRow) {
    tgtRow.innerHTML = _targetChipsHtml();
    _bindTargetChips(tgtRow);
  }
  // Re-paint the math readout block.
  const mathHost = byId('suntltestMath');
  if (mathHost) mathHost.innerHTML = renderMathReadout(weatherCams());
  // Start button only enabled when the tuple is mathematically valid.
  const startBtn = byId('suntltestStart');
  if (startBtn) startBtn.disabled = !isTargetValid(S.duration, S.targetLength) || !S.cam;
}

// Centralised UI toggle — hide the start button while a test is in
// flight so a fast clicker can't fire a second start before the
// poller has reset state. The cancel button mirrors the inverse.
export function setRunningUi(isRunning) {
  const start = byId('suntltestStart');
  const cancel = byId('suntltestCancel');
  if (start) {
    start.hidden = !!isRunning;
    start.disabled = !!isRunning;
  }
  if (cancel) {
    cancel.hidden = !isRunning;
    cancel.disabled = false;
  }
}
