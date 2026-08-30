// ─── netz/_tuning.js ────────────────────────────────────────────────────────
// The Fangnetz's PRIMARY radar — camera-wide capture/motion/tracking
// settings, one spoke each (see _settings_axes.js for why these and not
// object classes: every one of them runs before the pipeline has
// classified anything, so a per-class shape is a category error, not a
// missing feature).
//
// Ghost-track filtering (a boolean) and the three tracker presets (each
// a one-click shortcut across four fields at once) sit BELOW the chart
// as their own controls rather than forced onto spokes — a toggle has
// no continuum to drag along, and a preset writes several axes in one
// motion, which a single vertex can't represent.
import { qsa } from '../core/dom.js';
import { showToast } from '../core/toast.js';
import { renderTuneRadar } from './_radar.js';
import { bindTuneDrag } from './_tune_drag.js';
import { TUNE_SPECS, buildTuneAxes } from './_settings_axes.js';
import { patchTuning } from './_api.js';
import { netzState } from './_state.js';

const _TRACK_PRESETS = {
  careful: { spawn: 0.55, cont: 0.3, grace: 4, iou: 0.3 },
  balanced: { spawn: 0.5, cont: 0.2, grace: 6, iou: 0.2 },
  robust: { spawn: 0.45, cont: 0.15, grace: 10, iou: 0.15 },
};
const _TRACK_PRESET_LABELS = { careful: 'Vorsichtig', balanced: 'Ausgewogen', robust: 'Robust' };

function _effectiveTuning(st) {
  // Staged (dragged-but-not-committed) values overlay the server state so
  // the chart shows what the operator is mid-edit on, matching the
  // confidence radar's shownE().
  return { ...(st.tuning || {}), ...netzState.tuneStaged };
}

function _stagingHtml() {
  const n = Object.keys(netzState.tuneStaged).length;
  if (!n) return '';
  return (
    `<div class="netz-stage" role="group" aria-label="Ungespeicherte Änderungen">` +
    `<span>${n} ${n === 1 ? 'Wert' : 'Werte'} geändert</span>` +
    `<button type="button" class="netz-btn netz-btn--ghost" data-tune-discard>Verwerfen</button>` +
    `<button type="button" class="netz-btn" data-tune-apply>Übernehmen</button></div>`
  );
}

function _ghostToggleHtml(tuning) {
  const checked = tuning.track_filter_ghosts !== false;
  return (
    `<label class="erk-track-toggle"><span class="erk-track-toggle-text">` +
    `<span class="erk-track-toggle-name">Ghost-Spuren in Aufnahmen ausblenden</span>` +
    `<span class="erk-track-toggle-sub">Spuren, deren beste Konfidenz nie über der ` +
    `Spawn-Schwelle lag, werden nach der Aufnahme aus dem Track-Sidecar entfernt.</span>` +
    `</span><input type="checkbox" data-tune-ghost class="switch-input"` +
    `${checked ? ' checked' : ''}><span class="switch"></span></label>`
  );
}

function _presetsHtml() {
  const buttons = Object.keys(_TRACK_PRESETS)
    .map(
      (k) =>
        `<button type="button" class="erk-track-preset" data-tune-preset="${k}">` +
        `${_TRACK_PRESET_LABELS[k]}</button>`,
    )
    .join('');
  return (
    `<div class="erk-track-presets" role="group" aria-label="Tracking-Vorlagen">` +
    `<span class="erk-track-presets-lbl">Vorlage anwenden (Spawn/Fortsetzung/Gnadenfrist/IoU):</span>` +
    `${buttons}</div>`
  );
}

export function tuningHtml(st) {
  const tuning = _effectiveTuning(st);
  const axes = buildTuneAxes(tuning);
  // _tune_drag.js resolves the dragged vertex through netzState.tuneAxes.
  // Without this assignment its lookup returns null and _onDown bails on
  // EVERY pointerdown — the vertex silently never moves, which reads as
  // "didn't drag far enough" rather than as a bug.
  netzState.tuneAxes = axes;
  const side =
    Math.min(window.innerWidth || 375, 420) > 420
      ? 340
      : Math.max(240, Math.min((window.innerWidth || 375) - 32, 340));
  return (
    `<div class="netz-tune-chart">${renderTuneRadar({ axes, side, interactive: true })}</div>` +
    `<div class="netz-tune-controls">` +
    _presetsHtml() +
    _ghostToggleHtml(tuning) +
    `</div>` +
    _stagingHtml()
  );
}

function _repaintVertex(host, key, e) {
  const wrap = host.querySelector('.netz-tune-chart');
  if (!wrap) return false;
  const st = netzState.state;
  const tuning = _effectiveTuning(st);
  const axes = buildTuneAxes(tuning);
  const i = axes.findIndex((a) => a.key === key);
  if (i < 0) return false;
  axes[i] = { ...axes[i], E: e };
  netzState.tuneAxes = axes;
  const side = wrap.querySelector('.netz-svg')?.getAttribute('width') || 340;
  wrap.innerHTML = renderTuneRadar({ axes, side: Number(side), interactive: true });
  return true;
}

export function bindTuning(host, onRepaint) {
  const onStage = (key, raw, alreadySaved) => {
    if (alreadySaved) {
      // Long-press reset already PATCHed the server; drop any stale
      // staged value for this key so a later Übernehmen doesn't
      // resend a value that no longer reflects the reset.
      delete netzState.tuneStaged[key];
      if (netzState.state?.tuning) netzState.state.tuning[key] = raw;
      return;
    }
    netzState.tuneStaged[key] = raw;
  };
  bindTuneDrag(host, onRepaint, onStage);
  // A vertex mid-drag repaints itself (same reasoning as the confidence
  // radar's netz:vertexmove): the pointer capture set in _tune_drag.js's
  // _onDown keeps targeting the original node regardless of this innerHTML
  // rebuild, but any FUTURE drag needs fresh listeners on the fresh nodes.
  host.addEventListener('netz:tunevertexmove', (ev) => {
    if (_repaintVertex(host, ev.detail.key, ev.detail.e)) bindTuneDrag(host, onRepaint, onStage);
  });

  host.querySelector('[data-tune-apply]')?.addEventListener('click', async () => {
    const fields = { ...netzState.tuneStaged };
    const res = await patchTuning(netzState.camId, fields);
    if (res.ok) {
      if (netzState.state) netzState.state.tuning = { ...netzState.state.tuning, ...fields };
      netzState.tuneStaged = {};
      showToast('Fangnetz übernommen.', 'success');
    } else {
      showToast('Konnte nicht gespeichert werden: ' + (res.error || '—'), 'error');
    }
    onRepaint();
  });
  host.querySelector('[data-tune-discard]')?.addEventListener('click', () => {
    netzState.tuneStaged = {};
    onRepaint();
  });

  host.querySelector('[data-tune-ghost]')?.addEventListener('change', async (e) => {
    const res = await patchTuning(netzState.camId, { track_filter_ghosts: e.target.checked });
    if (res.ok && netzState.state) {
      netzState.state.tuning = { ...netzState.state.tuning, track_filter_ghosts: e.target.checked };
    } else if (!res.ok) {
      showToast('Konnte nicht gespeichert werden: ' + (res.error || '—'), 'error');
      e.target.checked = !e.target.checked;
    }
  });

  qsa('[data-tune-preset]', host).forEach((btn) =>
    btn.addEventListener('click', async () => {
      const preset = _TRACK_PRESETS[btn.dataset.tunePreset];
      if (!preset) return;
      const fields = {
        track_spawn_min_score: preset.spawn,
        track_continue_min_score: preset.cont,
        track_miss_grace_seconds: preset.grace,
        track_iou_match_threshold: preset.iou,
      };
      const res = await patchTuning(netzState.camId, fields);
      if (res.ok) {
        if (netzState.state) netzState.state.tuning = { ...netzState.state.tuning, ...fields };
        delete netzState.tuneStaged.track_miss_grace_seconds;
        delete netzState.tuneStaged.track_iou_match_threshold;
        showToast(
          `Vorlage gespeichert · ${_TRACK_PRESET_LABELS[btn.dataset.tunePreset]}`,
          'success',
        );
      } else {
        showToast('Vorlage konnte nicht gespeichert werden: ' + (res.error || '—'), 'error');
      }
      onRepaint();
    }),
  );

  qsa('[data-tune-axis-label]', host).forEach((b) =>
    b.addEventListener('click', () => {
      const spec = TUNE_SPECS[b.dataset.tuneAxisLabel];
      if (spec) showToast(`${spec.label}\n${spec.hint}`, 'info', { lifetime: 7000 });
    }),
  );
}
