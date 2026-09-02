// ─── vplayer/panels/_reclassify.js ─────────────────────────────────────────
// The correction sheet: say what this actually was, or mark it a false
// alarm.
//
// THE LEDGER RULE IS THE BACKEND'S, AND IT DEPENDS ON HOW WE POST.
// events.py books a correction only when BOTH conjuncts hold:
//
//     if labels and event["top_label"] != prev_top:
//
// Two shapes are excluded on purpose, and both exclusions are only
// correct because the editor sends ONE TOGGLE PER REQUEST:
//
//   · an emptied list — "motion" is then OUR fallback, not the operator
//     saying it was motion. Booking it would invent a positive example
//     of a class nobody asserted.
//   · the intermediate state of a two-tap correction. Changing
//     cat → squirrel arrives as remove-cat, then add-squirrel. Booking
//     the removal would file a spurious correction against whatever
//     happened to remain. Requiring a non-empty list means only the
//     second tap counts.
//
// So this sheet POSTS THE WHOLE LABEL SET after a single toggle, the
// way the existing bubble editor does. Batching several edits into one
// request would look tidier and would quietly change which corrections
// the corpus records.

import { esc } from '../../core/dom.js';
import { OBJ_LABEL } from '../../core/icons.js';

/** The classes an operator can correct to. */
const _CHOICES = ['person', 'cat', 'dog', 'bird', 'squirrel', 'fox', 'hedgehog', 'car'];

/**
 * PURE: the label set produced by toggling one class.
 *
 * One toggle in, one full set out — the shape the endpoint takes.
 */
export function toggleLabel(current, label) {
  const set = new Set(Array.isArray(current) ? current : []);
  if (set.has(label)) set.delete(label);
  else set.add(label);
  return [...set];
}

/**
 * PURE: the request for a label change.
 *
 * @returns {{url: string, method: string, body: object}|null}
 */
export function labelsRequestFor(item, labels) {
  if (!item || !item.camera_id || !item.event_id) return null;
  return {
    url:
      `/api/camera/${encodeURIComponent(item.camera_id)}` +
      `/events/${encodeURIComponent(item.event_id)}/labels`,
    method: 'POST',
    body: { labels },
  };
}

function _sheetHtml(active) {
  const set = new Set(active || []);
  const chips = _CHOICES.map(
    (c) =>
      `<button type="button" class="vp-seg" data-label="${esc(c)}" ` +
      `aria-pressed="${set.has(c) ? 'true' : 'false'}">` +
      `<span class="vp-seg-label">${esc(OBJ_LABEL[c] || c)}</span></button>`,
  ).join('');
  return (
    // The sheet edits the CLIP's label set, not the row it was opened
    // from — POST …/events/<id>/labels has no per-detection form and the
    // ledger is keyed by event. The title says so, because a sheet
    // headed "Erkennung korrigieren" reads as a promise to change one
    // row out of four and would quietly break it for the others.
    `<div class="vp-sheet-title">Erkennungen dieser Aufnahme</div>` +
    `<div class="vp-segbar vp-segbar--wrap">${chips}</div>` +
    // Clearing every label is how an operator says "nothing was here".
    // The backend deliberately books NO correction for an emptied list,
    // so this is a data fix, not a judgement — the copy says so.
    `<div class="vp-pnl-debug-bar">` +
    `<button type="button" class="vp-pnl-btn" data-act="none">Fehlalarm · alle entfernen</button>` +
    `<button type="button" class="vp-pnl-btn" data-act="close">Fertig</button></div>`
  );
}

/**
 * Open the correction sheet for an item.
 *
 * @param {HTMLElement} host
 * @param {object} item
 * @param {object} deps  { request, onSaved(result), onError }
 * @returns {{teardown: () => void}|null}
 */
export function openReclassify(host, item, deps = {}) {
  if (!host || !item) return null;
  let labels = Array.isArray(item.labels) ? [...item.labels] : [];

  const sheet = document.createElement('div');
  sheet.className = 'vp-sheet';
  sheet.innerHTML = _sheetHtml(labels);
  host.appendChild(sheet);

  const close = () => sheet.remove();

  const post = async (next) => {
    const req = labelsRequestFor(item, next);
    if (!req) return;
    try {
      const res = await deps.request(req.url, {
        method: req.method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req.body),
      });
      labels = next;
      sheet.innerHTML = _sheetHtml(labels);
      deps.onSaved?.(res, labels);
    } catch (e) {
      deps.onError?.('Speichern fehlgeschlagen: ' + (e?.message || e));
    }
  };

  const onClick = (ev) => {
    const chip = ev.target.closest?.('[data-label]');
    if (chip) {
      // One toggle, one request — see the header for why batching would
      // change which corrections the corpus records.
      post(toggleLabel(labels, chip.dataset.label));
      return;
    }
    const act = ev.target.closest?.('[data-act]')?.dataset.act;
    if (act === 'none') post([]);
    else if (act === 'close') close();
  };
  sheet.addEventListener('click', onClick);

  return {
    teardown: () => {
      sheet.removeEventListener('click', onClick);
      close();
    },
  };
}
