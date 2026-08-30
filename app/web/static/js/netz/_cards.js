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

import { esc, qsa } from '../core/dom.js';
import { showToast } from '../core/toast.js';
import { patchTuning } from './_api.js';
import { TUNE_COMBOS, TUNE_GROUPS, TUNE_SPECS, buildTuneAxes } from './_settings_axes.js';
import { renderTuneRadar, tuneGroupLegendHtml } from './_tune_radar.js';
import {
  applySaved,
  camState,
  clearStagedFor,
  effectiveTuning,
  netzState,
  stagedCountFor,
  stagedFor,
  unstage,
} from './_state.js';

const _TRACK_PRESETS = {
  careful: { spawn: 0.55, cont: 0.3, grace: 4, iou: 0.3 },
  balanced: { spawn: 0.5, cont: 0.2, grace: 6, iou: 0.2 },
  robust: { spawn: 0.45, cont: 0.15, grace: 10, iou: 0.15 },
};
const _TRACK_PRESET_LABELS = { careful: 'Vorsichtig', balanced: 'Ausgewogen', robust: 'Robust' };
const _ROLE_DE = { security: 'Sicherheit', wildlife: 'Wildtiere', garden: 'Garten' };

// ── render ────────────────────────────────────────────────────────────

function _confidenceLine(st) {
  // Per-class confidence as plain TEXT, not a second radar. The values are
  // still learned from the Telegram verdicts and still enforced; this page
  // just stopped drawing a chart for them.
  const axes = st.axes || [];
  if (!axes.length) return '';
  const parts = axes
    .map((a) => {
      const pct = Number.isFinite(Number(a.push)) ? `${Math.round(Number(a.push) * 100)} %` : '—';
      return `${esc(a.label)} ${pct}`;
    })
    .join(' · ');
  return `<div class="netz-card-conf"><b>Meldeschwelle je Klasse</b><span>${parts}</span></div>`;
}

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

function _ghostHtml(tuning) {
  return (
    `<label class="netz-card-ghost"><span>Ghost-Spuren ausblenden</span>` +
    `<input type="checkbox" data-tune-ghost class="switch-input"` +
    `${tuning.track_filter_ghosts !== false ? ' checked' : ''}>` +
    `<span class="switch"></span></label>`
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
  const axes = buildTuneAxes(tuning);
  netzState.tuneAxes[cam.id] = axes;
  const role = _ROLE_DE[st.role] || st.role || '';
  const focused = netzState.focusCam === cam.id ? ' is-focus' : '';
  return (
    `<article class="netz-card${focused}" data-cam="${esc(cam.id)}">` +
    `<header class="netz-card-hd"><h4>${esc(cam.name)}</h4>` +
    (role ? `<span class="netz-card-role">${esc(role)}</span>` : '') +
    `</header>` +
    `<div class="netz-card-chart">${renderTuneRadar({ axes, interactive: true })}</div>` +
    _confidenceLine(st) +
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
  const cams = netzState.cameras || [];
  if (!cams.length) {
    host.innerHTML = `<div class="netz-empty"><div class="netz-empty-sub">Keine Kamera konfiguriert.</div></div>`;
    return;
  }
  host.innerHTML =
    _chipsHtml() +
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

  card.querySelector('[data-tune-ghost]')?.addEventListener('change', async (ev) => {
    await _save(
      camId,
      { track_filter_ghosts: ev.target.checked },
      'Erkennungsprofil übernommen.',
      onRepaint,
    );
  });

  qsa('[data-tune-preset]', card).forEach((btn) =>
    btn.addEventListener('click', async () => {
      const p = _TRACK_PRESETS[btn.dataset.tunePreset];
      if (!p) return;
      // A preset writes four fields at once; drop any staged value for the
      // two it overlaps so a later "Übernehmen" cannot resurrect them.
      unstage(camId, 'track_miss_grace_seconds');
      unstage(camId, 'track_iou_match_threshold');
      await _save(
        camId,
        {
          track_spawn_min_score: p.spawn,
          track_continue_min_score: p.cont,
          track_miss_grace_seconds: p.grace,
          track_iou_match_threshold: p.iou,
        },
        `Vorlage gespeichert · ${_TRACK_PRESET_LABELS[btn.dataset.tunePreset]}`,
        onRepaint,
      );
    }),
  );

  qsa('[data-tune-axis-label]', card).forEach((b) =>
    b.addEventListener('click', () => {
      const spec = TUNE_SPECS[b.dataset.tuneAxisLabel];
      if (spec) showToast(`${spec.label}\n${spec.hint}`, 'info', { lifetime: 7000 });
    }),
  );
}

export function bindCards(host, onRepaint) {
  qsa('[data-netz-cam]', host).forEach((b) =>
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
