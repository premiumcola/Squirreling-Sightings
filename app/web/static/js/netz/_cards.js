// ─── netz/_cards.js ────────────────────────────────────────────────────────
// One camera's net BODY: the settings radar, its controls, and the save
// path. The panel SHELL around it (header, camera identity, the
// Netz/Verlauf toggle, the frozen-values box) lives in netz/_panel.js,
// which mounts one of these beside every camera's Live-Feed tile.
//
// EVERY write takes its camera id from `card.dataset.cam` — the DOM node
// the operator actually touched — never from a module-level "current
// camera". With N panels on the page a module scalar is exactly how a drag
// on camera B ends up PATCHing camera A, and it fails silently (the
// request succeeds, against the wrong camera).
//
// For the same reason every querySelector here is scoped to `card`, not
// to the page: `document.querySelector('[data-tune-apply]')` would find
// the FIRST panel's button regardless of which one was clicked.

import { esc, qsa } from '../core/dom.js';
import { showToast } from '../core/toast.js';
import { patchTuning } from './_api.js';
import { TUNE_COMBOS, TUNE_GROUPS, TUNE_SPECS, buildTuneAxes } from './_settings_axes.js';
import { renderTuneRadar } from './_tune_radar.js';
import { buildClassAxes, classAxisHint, classAxisSpec } from './_class_rows.js';
import {
  applySaved,
  axisFor,
  camState,
  clearStagedFor,
  effectiveTuning,
  netzState,
  stageValue,
  stagedCountFor,
  stagedFor,
} from './_state.js';

const _TRACK_PRESETS = {
  careful: { spawn: 0.55, cont: 0.3, grace: 4, iou: 0.3 },
  balanced: { spawn: 0.5, cont: 0.2, grace: 6, iou: 0.2 },
  robust: { spawn: 0.45, cont: 0.15, grace: 10, iou: 0.15 },
};
const _TRACK_PRESET_LABELS = { careful: 'Vorsichtig', balanced: 'Ausgewogen', robust: 'Robust' };

// ── render ────────────────────────────────────────────────────────────

function _stagingHtml(camId) {
  const n = stagedCountFor(camId);
  if (!n) return '';
  return (
    `<div class="netz-stage" role="group" aria-label="Ungespeicherte Änderungen">` +
    `<span>${n} ${n === 1 ? 'Wert' : 'Werte'} geändert</span>` +
    `<button type="button" class="netz-btn netz-btn--ghost" data-tune-discard>Verwerfen</button>` +
    `<button type="button" class="netz-btn" data-tune-apply>Übernehmen</button></div>`
  );
}

function _presetsHtml() {
  return (
    `<div class="erk-track-presets" role="group" aria-label="Tracking-Vorlagen">` +
    `<span class="erk-track-presets-lbl">Vorlage:</span>` +
    Object.keys(_TRACK_PRESETS)
      .map(
        (k) =>
          `<button type="button" class="erk-track-preset" data-tune-preset="${k}">` +
          `${_TRACK_PRESET_LABELS[k]}</button>`,
      )
      .join('') +
    `</div>`
  );
}

// One switch does not need a row of its own — it used to own a full
// 44 px line under the presets for a single boolean. As a chip it sits at
// the end of the preset row, keeps the 44 px target, and reports its
// state through aria-pressed instead of a second label.
function _ghostHtml(tuning) {
  const on = tuning.track_filter_ghosts !== false;
  return (
    `<button type="button" class="netz-chip-toggle" data-tune-ghost ` +
    `aria-pressed="${on ? 'true' : 'false'}" aria-label="Ghost-Spuren ausblenden" ` +
    `title="Ghost-Spuren ausblenden">` +
    `<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true" fill="none" ` +
    `stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">` +
    `<path d="M12 3a7 7 0 0 0-7 7v11l2.5-2 2.5 2 2-2 2 2 2.5-2 2.5 2V10a7 7 0 0 0-7-7Z"/>` +
    `<path d="M9.5 10.5h.01M14.5 10.5h.01"/></svg>Ghost</button>`
  );
}

/** The radar + its controls + the staging bar for ONE camera — everything
 *  below the panel's own header, which netz/_panel.js owns. Before this
 *  camera's /api/netz/state has resolved (camState is still null) it
 *  renders the calm "wird geladen …" state instead of a chart with
 *  nothing to draw. */
export function netBodyHtml(cam) {
  const st = camState(cam.id);
  if (!st) {
    return `<div class="netz-empty"><div class="netz-empty-sub">wird geladen …</div></div>`;
  }
  const tuning = effectiveTuning(cam.id);
  // ONE net per camera. The camera-wide settings first, so each colour
  // group keeps a contiguous arc, then this camera's per-class
  // Meldeschwellen — which classes those are comes from the camera's own
  // Klassen-Filter, so the spoke count differs from panel to panel.
  const axes = [...buildTuneAxes(tuning), ...buildClassAxes(st)];
  netzState.tuneAxes[cam.id] = axes;
  return (
    `<div class="netz-card-chart">${renderTuneRadar({ axes, interactive: true })}</div>` +
    `<div class="netz-card-controls">${_presetsHtml()}${_ghostHtml(tuning)}</div>` +
    _stagingHtml(cam.id)
  );
}

/** "Was zusammen wirkt" — cross-axis interaction notes. Camera-independent
 *  reference text, so it is shown ONCE for the whole Live-Feed section
 *  (netz/_panel.js mounts it behind a header info button) rather than
 *  repeated on every panel. */
export function combosHtml() {
  return (
    `<div class="netz-combos"><b>Was zusammen wirkt</b>` +
    TUNE_COMBOS.map((c) => {
      const dots = c.groups
        .map(
          (g) =>
            `<i style="background:${esc((TUNE_GROUPS[g] || {}).color || '#888')}" ` +
            `title="${esc((TUNE_GROUPS[g] || {}).label || g)}"></i>`,
        )
        .join('');
      return `<p><span class="netz-combo-dots">${dots}</span>${esc(c.text)}</p>`;
    }).join('') +
    `</div>`
  );
}

/** "Werte, die fest bleiben" — reference rows for ONE camera. Was rendered
 *  for `netzState.cameras[0]` only, back when the box lived once in a
 *  shared header regardless of which camera the operator was looking at;
 *  now every panel has its own, so this always reflects the RIGHT camera. */
export function frozenListHtml(camId) {
  const st = camState(camId);
  const rows = ((st && st.frozen) || [])
    .map((f) => `<li><code>${esc(f.key)}</code><span>${esc(f.de)}</span></li>`)
    .join('');
  return rows ? `<ul>${rows}</ul>` : '';
}

// ── bind ──────────────────────────────────────────────────────────────

async function _save(camId, fields, okMsg, onRepaint) {
  const res = await patchTuning(camId, fields);
  if (res.ok) {
    applySaved(camId, res.effective || fields);
    showToast(okMsg, 'success');
  } else {
    showToast('Konnte nicht gespeichert werden: ' + (res.error || '—'), 'error');
  }
  onRepaint();
}

/** Tap a spoke's label → what that axis does. One lookup covers both
 *  concerns on the net; a class axis whose Meldung is off says WHY it is
 *  greyed out, which is the whole job of a disabled control's hint. */
function _bindAxisHints(card, camId) {
  qsa('[data-tune-axis-label]', card).forEach((b) =>
    b.addEventListener('click', () => {
      const key = b.dataset.tuneAxisLabel;
      const spec = TUNE_SPECS[key] || classAxisSpec(key);
      if (!spec) return;
      const hint = TUNE_SPECS[key] ? spec.hint : classAxisHint(axisFor(camId, key));
      showToast(`${spec.label}\n${hint}`, 'info', { lifetime: 7000 });
    }),
  );
}

/** Wire the interactive controls inside ONE panel's net body. `card` is
 *  the panel root — the camera id always comes from `card.dataset.cam`,
 *  never from a parameter the caller might mix up between panels. */
export function bindNetBody(card, onRepaint) {
  const camId = card.dataset.cam;

  card.querySelector('[data-tune-apply]')?.addEventListener('click', async () => {
    const fields = { ...stagedFor(camId) };
    if (!Object.keys(fields).length) return;
    clearStagedFor(camId);
    await _save(camId, fields, 'Erkennungsprofil übernommen.', onRepaint);
  });

  card.querySelector('[data-tune-discard]')?.addEventListener('click', () => {
    clearStagedFor(camId);
    onRepaint();
  });

  card.querySelector('[data-tune-ghost]')?.addEventListener('click', async (ev) => {
    const wasOn = ev.currentTarget.getAttribute('aria-pressed') === 'true';
    await _save(camId, { track_filter_ghosts: !wasOn }, 'Erkennungsprofil übernommen.', onRepaint);
  });

  qsa('[data-tune-preset]', card).forEach((btn) =>
    btn.addEventListener('click', () => {
      const p = _TRACK_PRESETS[btn.dataset.tunePreset];
      if (!p) return;
      // A preset STAGES its four fields, it does not commit them. Clicking
      // one used to overwrite four axes on the spot with nothing to
      // return to — „dann verdreht's ja alles, dann komm ich nicht
      // zurück". Staged, the bar's „Verwerfen" IS the way back, and it
      // costs no extra control on an already busy panel.
      stageValue(camId, 'track_spawn_min_score', p.spawn);
      stageValue(camId, 'track_continue_min_score', p.cont);
      stageValue(camId, 'track_miss_grace_seconds', p.grace);
      stageValue(camId, 'track_iou_match_threshold', p.iou);
      showToast(
        `Vorlage ${_TRACK_PRESET_LABELS[btn.dataset.tunePreset]} vorgemerkt — ` +
          `„Übernehmen" speichert, „Verwerfen" nimmt sie zurück.`,
        'info',
        { lifetime: 6000 },
      );
      onRepaint();
    }),
  );

  _bindAxisHints(card, camId);
}
