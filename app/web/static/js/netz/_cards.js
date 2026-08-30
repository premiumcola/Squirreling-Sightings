// ─── netz/_cards.js ────────────────────────────────────────────────────────
// One card per camera: the settings radar, its controls, and the save
// path. Replaces the old single-camera _tuning.js.
//
// EVERY write takes its camera id from `card.dataset.cam` — the DOM node
// the operator actually touched — never from a module-level "current
// camera". With N cards in one host a module scalar is exactly how a drag
// on camera B ends up PATCHing camera A, and it fails silently (the
// request succeeds, against the wrong camera).
//
// For the same reason every querySelector here is scoped to `card`, not
// to the host: `host.querySelector('[data-tune-apply]')` finds the FIRST
// card's button regardless of which one was clicked.

import { byId, esc, qsa } from '../core/dom.js';
import { showToast } from '../core/toast.js';
import { patchTuning } from './_api.js';
import { TUNE_COMBOS, TUNE_GROUPS, TUNE_SPECS, buildTuneAxes } from './_settings_axes.js';
import { renderTuneRadar, tuneGroupLegendHtml } from './_tune_radar.js';
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
const _ROLE_DE = { security: 'Sicherheit', wildlife: 'Wildtiere', garden: 'Garten' };

// The camera chips render into the section HEADER, not into the body
// host: #netzBody is swapped wholesale between the Netz and the Verlauf
// view, and the chips belong to the Netz. The slot sits beside the
// Verlauf button, which puts them top-right on desktop (32-netz.css moves
// them onto their own strip below the title on a phone).
const CHIPS_ID = 'netzCamChips';

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

function _cardHtml(cam) {
  const st = camState(cam.id);
  if (!st) {
    return (
      `<article class="netz-card" data-cam="${esc(cam.id)}">` +
      `<header class="netz-card-hd"><h4>${esc(cam.name)}</h4></header>` +
      `<div class="netz-empty"><div class="netz-empty-sub">wird geladen …</div></div>` +
      `</article>`
    );
  }
  const tuning = effectiveTuning(cam.id);
  // ONE net per camera. The camera-wide settings first, so each colour
  // group keeps a contiguous arc, then this camera's per-class
  // Meldeschwellen — which classes those are comes from the camera's own
  // Klassen-Filter, so the spoke count differs from card to card.
  const axes = [...buildTuneAxes(tuning), ...buildClassAxes(st)];
  netzState.tuneAxes[cam.id] = axes;
  const role = _ROLE_DE[st.role] || st.role || '';
  const focused = netzState.focusCam === cam.id ? ' is-focus' : '';
  return (
    `<article class="netz-card${focused}" data-cam="${esc(cam.id)}">` +
    `<header class="netz-card-hd"><h4>${esc(cam.name)}</h4>` +
    (role ? `<span class="netz-card-role">${esc(role)}</span>` : '') +
    `</header>` +
    `<div class="netz-card-chart">${renderTuneRadar({ axes, interactive: true })}</div>` +
    `<div class="netz-card-controls">${_presetsHtml()}${_ghostHtml(tuning)}</div>` +
    _stagingHtml(cam.id) +
    `</article>`
  );
}

function _chipsHtml() {
  const cams = netzState.cameras || [];
  if (cams.length < 2) return '';
  return (
    `<div class="netz-pills netz-cams">` +
    cams
      .map(
        (c) =>
          `<button type="button" class="netz-pill${
            netzState.focusCam === c.id ? ' is-active' : ''
          }" data-netz-cam="${esc(c.id)}">${esc(c.name)}</button>`,
      )
      .join('') +
    `</div>`
  );
}

/** Paint the header's camera slot. Cleared in the Verlauf view, which
 *  has camera chips of its own inside the list. */
export function renderCamChips() {
  const el = byId(CHIPS_ID);
  if (el) el.innerHTML = netzState.view === 'netz' ? _chipsHtml() : '';
}

function _combosHtml() {
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

function _frozenHtml() {
  // A plain box, not a <details>. "Werte, die fest bleiben" is reference
  // material the operator should be able to SEE without a click — the
  // difference between frozen and forgotten is whether it is readable.
  const first = netzState.cameras[0];
  const st = first ? camState(first.id) : null;
  const rows = ((st && st.frozen) || [])
    .map((f) => `<li><code>${esc(f.key)}</code><span>${esc(f.de)}</span></li>`)
    .join('');
  if (!rows) return '';
  return `<div class="netz-frozen-box"><b>Werte, die fest bleiben</b><ul>${rows}</ul></div>`;
}

export function renderCards(host) {
  renderCamChips();
  const cams = netzState.cameras || [];
  if (!cams.length) {
    host.innerHTML = `<div class="netz-empty"><div class="netz-empty-sub">Keine Kamera konfiguriert.</div></div>`;
    return;
  }
  host.innerHTML =
    tuneGroupLegendHtml() +
    `<div class="netz-cards">${cams.map((c) => _cardHtml(c)).join('')}</div>` +
    _combosHtml() +
    _frozenHtml();
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

function _bindCard(card, onRepaint) {
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
      // costs no extra control on an already busy card.
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

  qsa('[data-tune-axis-label]', card).forEach((b) =>
    b.addEventListener('click', () => {
      const key = b.dataset.tuneAxisLabel;
      const spec = TUNE_SPECS[key] || classAxisSpec(key);
      if (!spec) return;
      // A class axis whose Meldung is off says WHY it is greyed out —
      // that is the whole job of a disabled control's hint.
      const hint = TUNE_SPECS[key] ? spec.hint : classAxisHint(axisFor(camId, key));
      showToast(`${spec.label}\n${hint}`, 'info', { lifetime: 7000 });
    }),
  );
}

export function bindCards(host, onRepaint) {
  qsa('[data-netz-cam]', byId(CHIPS_ID) || host).forEach((b) =>
    b.addEventListener('click', () => {
      netzState.focusCam = netzState.focusCam === b.dataset.netzCam ? null : b.dataset.netzCam;
      onRepaint();
      host
        .querySelector(`.netz-card[data-cam="${CSS.escape(b.dataset.netzCam)}"]`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
    }),
  );
  qsa('.netz-card', host).forEach((card) => _bindCard(card, onRepaint));
}
