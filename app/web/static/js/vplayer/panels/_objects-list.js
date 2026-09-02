// ─── vplayer/panels/_objects-list.js ───────────────────────────────────────
// What was detected in this recording: one row per object, each row a
// touch target that opens the correction sheet.
//
// The row carries four facts and each earns its place:
//   · WHICH object — the class, with its per-clip number and its own
//     colour, so a row, its lane on the timeline and its box on the
//     picture are visibly the same thing;
//   · HOW SURE — the best score the track reached, not its last one;
//   · WHICH MODEL said so — the cascade stage that produced the label.
//     A bird called by the bird classifier and a bird called by the
//     object detector are different claims, and only one of them is
//     worth arguing with;
//   · WHEN — the span it was tracked for.
//
// Edit and delete are per row and 44 px, because correcting one wrong
// label out of four is the actual job; a single verdict on the whole
// clip is what the corpus already has too much of.

import { esc } from '../../core/dom.js';
import { OBJ_LABEL } from '../../core/icons.js';
import { liveTrackColor } from '../../core/track-color.js';
import { PLACEHOLDER, pctLabel, spanLabel } from '../_helpers.js';
import { modelLabel } from './_helpers.js';

const _EDIT_SVG =
  '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>';
const _DEL_SVG =
  '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" aria-hidden="true">' +
  '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>';

/** PURE: the one-line summary a row shows under its title. */
export function rowDetail(row, models) {
  const span = row.t0 == null ? PLACEHOLDER : spanLabel(row.t0, row.t1);
  return `${span} · ${modelLabel(row.model, models)}`;
}

function _rowHtml(row, models) {
  const cls = row.label ? OBJ_LABEL[row.label] || row.label : 'Unbekannt';
  const colour = row.colour || (row.num == null ? 'var(--muted)' : liveTrackColor(row.num));
  const num = row.num == null ? '' : `<span class="vp-pnl-num">#${esc(String(row.num))}</span>`;
  return (
    `<div class="vp-pnl-row vp-pnl-obj" data-key="${esc(row.key)}" ` +
    `style="--vp-lane-colour:${esc(colour)}">` +
    `${num}<span class="vp-pnl-cls">${esc(cls)}</span>` +
    `<span class="vp-pnl-score">${esc(pctLabel(row.score))}</span>` +
    `<button type="button" class="vp-pnl-iconbtn" data-act="edit" ` +
    `aria-label="Erkennung korrigieren">${_EDIT_SVG}</button>` +
    `<button type="button" class="vp-pnl-iconbtn" data-act="del" ` +
    `aria-label="Erkennung entfernen">${_DEL_SVG}</button>` +
    `<span class="vp-pnl-reason">${esc(rowDetail(row, models))}</span>` +
    `</div>`
  );
}

/**
 * Render the detected-object list.
 *
 * @param {HTMLElement} host
 * @param {object} deps  { onEdit(row), onDelete(row) }
 * @returns {{update, teardown}|null}
 */
export function renderObjectsList(host, deps = {}) {
  if (!host) return null;
  let rows = [];

  const onClick = (ev) => {
    const btn = ev.target.closest?.('[data-act]');
    const rowEl = ev.target.closest?.('[data-key]');
    if (!rowEl) return;
    const row = rows.find((r) => r.key === rowEl.dataset.key);
    if (!row) return;
    if (btn?.dataset.act === 'edit') deps.onEdit?.(row, rowEl);
    else if (btn?.dataset.act === 'del') deps.onDelete?.(row, rowEl);
  };
  host.addEventListener('click', onClick);

  return {
    update: (nextRows, models) => {
      rows = Array.isArray(nextRows) ? nextRows : [];
      host.innerHTML = rows.length
        ? rows.map((r) => _rowHtml(r, models)).join('')
        : `<div class="vp-pnl-empty">Keine Objekte in dieser Aufnahme</div>`;
    },
    teardown: () => {
      host.removeEventListener('click', onClick);
      host.innerHTML = '';
    },
  };
}
