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
// ONE CONTROL PER ROW, AND IT IS THE CORRECTION SHEET. A per-row DELETE
// was rendered here and wired to nothing, and it stays gone. Three facts
// decided that, in this order:
//
//   · NO BACKEND EXPRESSES IT. Every mutating route is whole-event
//     (delete / labels / confirm) or whole-sidecar (DELETE
//     /api/tracking/<id> removes the entire tracks.json). The only
//     per-track pruning in the tree, tracking_worker/_ghosts.py::
//     prune_ghost_tracks, runs at BUILD time and carries its own TODO
//     saying the retroactive endpoint does not exist.
//   · THE ROW HAS NO ADDRESS TO SEND. The three bases key differently
//     and the list switches between them per event: `whole_clip` folds
//     untracked detections into a `class:<label>` bucket with
//     `track_id: null` (_clip_tally.py::_key_for), the sidecar numbers
//     tracks from a DIFFERENT tracker run, and the trigger frame is a
//     bare array index. "Delete row 2" means three different things.
//   · THE LEDGER CANNOT RECORD IT. record_verdict is keyed by event_id
//     alone and LedgerIndex joins last-write-wins per event, so a
//     per-object verdict has nowhere to land — the corpus, which is the
//     whole point of correcting, would learn nothing from the gesture.
//
// The one endpoint in reach, POST …/events/<id>/labels, edits the
// EVENT's label set. A trash icon wired to it would strike a class
// shared by other rows, leave this row on screen (the rows come from
// the detection aggregate, which that endpoint never touches), and —
// because a whole_clip row can carry a class that never entered
// `labels` — could ADD one. A button called "remove" that sometimes
// adds is worse than the inert one it replaced.
//
// Nothing was lost. Both verbs the operator asked for live one tap away
// in the sheet this row opens: reclassify by tapping another class,
// strike one wrong class by tapping it while active (the documented
// "Falscherkennung" gesture — see mediaview/panels/labels.js), or call
// the whole clip a false alarm with "alle entfernen".

import { subjectLabel } from '../../core/clip-species.js';
import { esc } from '../../core/dom.js';
import { liveTrackColor } from '../../core/track-color.js';
import { PLACEHOLDER, pctLabel, spanLabel } from '../_helpers.js';
import { modelLabel } from './_helpers.js';

const _EDIT_SVG =
  '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>';
/** PURE: the one-line summary a row shows under its title. */
export function rowDetail(row, models) {
  const span = row.t0 == null ? PLACEHOLDER : spanLabel(row.t0, row.t1);
  return `${span} · ${modelLabel(row.model, models)}`;
}

function _rowHtml(row, models) {
  // A named bird is called by its species, so two birds in one clip
  // read as two birds. Same rule as the Mediathek card's badge —
  // core/clip-species.js owns it, this does not restate it.
  const cls = subjectLabel(row.label, row.species) || 'Unbekannt';
  // A SPECIES is a different kind of answer from a class, and until now
  // "Grünfink" and "Vogel" sat in the same grey with nothing to tell
  // them apart — „bitte verdeutliche auch, wenn eben eine spezielle
  // Vogelspezies erkannt wurde". The cascade got further than the
  // detector did on this row; the marker says so, and the class it
  // refines follows in the row's own detail line.
  const named = !!(row.species && row.label === 'bird');
  const colour = row.colour || (row.num == null ? 'var(--muted)' : liveTrackColor(row.num));
  const num = row.num == null ? '' : `<span class="vp-pnl-num">#${esc(String(row.num))}</span>`;
  return (
    `<div class="vp-pnl-row vp-pnl-obj" data-key="${esc(row.key)}" ` +
    `style="--vp-lane-colour:${esc(colour)}">` +
    `${num}<span class="vp-pnl-cls${named ? ' is-species' : ''}">${esc(cls)}</span>` +
    `<span class="vp-pnl-score">${esc(pctLabel(row.score))}</span>` +
    `<button type="button" class="vp-pnl-iconbtn" data-act="edit" ` +
    `aria-label="Erkennungen dieser Aufnahme korrigieren">${_EDIT_SVG}</button>` +
    `<span class="vp-pnl-reason">${esc(rowDetail(row, models))}</span>` +
    `</div>`
  );
}

/**
 * Render the detected-object list.
 *
 * `update`'s third argument is the list's footnote (which basis the
 * rows came from, and whether a cap truncated them). It is null for
 * every event that predates the whole-clip aggregate, and the empty
 * string it then renders keeps that markup byte-identical to before.
 *
 * @param {HTMLElement} host
 * @param {object} deps  { onEdit(row, rowEl) }
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
  };
  host.addEventListener('click', onClick);

  return {
    update: (nextRows, models, note) => {
      rows = Array.isArray(nextRows) ? nextRows : [];
      const body = rows.length
        ? rows.map((r) => _rowHtml(r, models)).join('')
        : `<div class="vp-pnl-empty">Keine Objekte in dieser Aufnahme</div>`;
      host.innerHTML = body + (note ? `<div class="vp-pnl-note">${esc(note)}</div>` : '');
    },
    teardown: () => {
      host.removeEventListener('click', onClick);
      host.innerHTML = '';
    },
  };
}
