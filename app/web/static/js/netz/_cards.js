// ─── netz/_cards.js ────────────────────────────────────────────────────────
// One camera's net BODY: the settings radar, the staging bar, the ghost
// switch, and the save path. The panel SHELL around it (header, camera
// identity, the Netz/Verlauf toggle) lives in netz/_panel.js, which
// mounts one of these beside every camera's Live-Feed tile and composes
// ghostToggleHtml() into that header. The frozen-values box has no
// per-panel home any more — see frozenSectionHtml() below.
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
import { ghostIconSvg, ghostKeyText, netKeyHtml } from './_key.js';
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
  stagedCountFor,
  stagedFor,
} from './_state.js';

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

/** Bring ONE panel's staging bar in line with what is staged, WITHOUT
 *  touching the radar.
 *
 *  Staging used to run through the panel's full repaint: every drag
 *  release rebuilt the SVG — rings, spokes, polygon, every vertex and
 *  every foreignObject label — to add or drop a bar that is not even part
 *  of the chart. The net visibly flickered, and the vertex the finger had
 *  just released was a brand-new node. The bar is an absolutely
 *  positioned overlay inside the chart box, so it can come and go without
 *  the chart's size or content changing at all; this swaps only the bar
 *  and rewires its two buttons. */
export function syncStageBar(card, onRepaint) {
  const chart = card.querySelector('.netz-card-chart');
  if (!chart) return;
  chart.querySelector('.netz-stage')?.remove();
  chart.insertAdjacentHTML('beforeend', _stagingHtml(card.dataset.cam));
  _bindStageButtons(card, onRepaint);
}

// One switch does not need a row of its own. It has been a full 44 px
// line, then a text chip in a controls row under the chart — a row that
// cost the net exactly its own height on every panel ("da ist ja viel
// Freiraum … macht das Netz einfach viel größer"). Now it is an icon-only
// button in the panel header (netz/_panel.js composes it beside the
// Verlauf toggle), same 44 px target, state through aria-pressed.
//
// What a ghost track IS is a tooltip here AND a visible sentence in the
// key row under the net (netz/_key.js) — "ich weiß immer noch nicht, was
// das bedeutet", and a `title` is a thing no phone ever shows. Both read
// the same source, so the button and the sentence cannot disagree.
const _GHOST_TITLE = 'Ghost-Spuren ausblenden – ';

export function ghostToggleHtml(camId) {
  const on = effectiveTuning(camId).track_filter_ghosts !== false;
  const title = esc(_GHOST_TITLE + ghostKeyText(camId));
  return (
    `<button type="button" class="netz-view-btn" data-tune-ghost ` +
    `aria-pressed="${on ? 'true' : 'false'}" aria-label="${title}" title="${title}">` +
    `${ghostIconSvg(18)}</button>`
  );
}

/** The radar + the staging bar for ONE camera — everything below the
 *  panel's own header, which netz/_panel.js owns. Before this camera's
 *  /api/netz/state has resolved (camState is still null) it renders the
 *  calm "wird geladen …" state instead of a chart with nothing to draw.
 *
 *  `size` is the chart box's measured px size (netz/_panel.js measures
 *  it right before calling) — the radar is drawn AT that size, so the
 *  box is the only thing that decides how big the net is. The staging
 *  bar rides INSIDE the box as an overlay: it exists only while values
 *  are staged, and a bar that came and went below the chart would make
 *  the net jump by its own height every time.
 *
 *  The legend row below the chart is part of the body, so it is part of
 *  what the chart box has to share its height with — netProbeHtml keeps
 *  the measured box honest about that. */
export function netBodyHtml(cam, size = null) {
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
    `<div class="netz-card-chart">${renderTuneRadar({ axes, interactive: true, size })}` +
    `${_stagingHtml(cam.id)}</div>` +
    netKeyHtml(cam.id)
  );
}

/** The same body MINUS the radar: an empty chart box and the real key
 *  row. netz/_panel.js lays this out to measure the box the radar is
 *  about to be drawn into. Built here, beside netBodyHtml, so the two can
 *  never drift into measuring one structure and rendering another — the
 *  key's ghost sentence wraps to a second line on a phone, and that line
 *  is height the net does not get. */
export function netProbeHtml(camId) {
  return `<div class="netz-card-chart"></div>` + netKeyHtml(camId);
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

/** "Werte, die fest bleiben" — reference rows for ONE camera. FROZEN_KEYS
 *  (app/routes/_netz_helpers.py) is one flat constant sent identically to
 *  every camera, so any loaded camera's list is the whole answer — this
 *  stays per-camera only so a test fixture can catch a future regression
 *  where that stops being true. */
export function frozenListHtml(camId) {
  const st = camState(camId);
  const rows = ((st && st.frozen) || [])
    .map((f) => `<li><code>${esc(f.key)}</code><span>${esc(f.de)}</span></li>`)
    .join('');
  return rows ? `<ul>${rows}</ul>` : '';
}

/** The page-level home for "Werte, die fest bleiben" — folded into the
 *  same info box "Was zusammen wirkt" already uses (netz/_panel.js's
 *  initCombosInfo) instead of repeating identical content on every
 *  camera's panel. Reads whichever camera has state loaded first; since
 *  the list is camera-independent by construction, any one of them is
 *  the right answer. */
export function frozenSectionHtml() {
  const camId = (netzState.cameras || []).find((c) => camState(c.id))?.id;
  const rows = camId ? frozenListHtml(camId) : '';
  return rows ? `<div class="netz-frozen-box"><b>Werte, die fest bleiben</b>${rows}</div>` : '';
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

/** The staging bar's own two buttons. Split out of bindNetBody because
 *  the bar is swapped on its own (syncStageBar) whenever a drag stages a
 *  value, while the labels around it keep the listeners they already
 *  have. BOTH of these end in a real repaint, and should: Übernehmen
 *  writes to the server and Verwerfen puts every vertex back where the
 *  stored profile has it — the chart genuinely changes. */
function _bindStageButtons(card, onRepaint) {
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
}

/** Wire the interactive controls inside ONE panel's net body. `card` is
 *  the panel root — the camera id always comes from `card.dataset.cam`,
 *  never from a parameter the caller might mix up between panels. */
export function bindNetBody(card, onRepaint) {
  _bindStageButtons(card, onRepaint);
  _bindAxisHints(card, card.dataset.cam);
}

/** The ghost switch sits in the panel HEADER, which is rendered in both
 *  the net and the Verlauf view — so it is wired from the header's own
 *  bind (netz/_panel.js), not from bindNetBody, which only runs for the
 *  net. Same card-scoped rule: the camera is `card.dataset.cam`. */
export function bindGhostToggle(card, onRepaint) {
  const camId = card.dataset.cam;
  card.querySelector('[data-tune-ghost]')?.addEventListener('click', async (ev) => {
    const wasOn = ev.currentTarget.getAttribute('aria-pressed') === 'true';
    await _save(camId, { track_filter_ghosts: !wasOn }, 'Erkennungsprofil übernommen.', onRepaint);
  });
}
