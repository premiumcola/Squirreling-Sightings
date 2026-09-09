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
import { colors, OBJ_LABEL, objIconSvg } from '../../core/icons.js';

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

// THE SAME BUBBLES THE SPECIES SHEET USES — „Mach den chooser im video
// auch so cool mit den Bubbles für alle arten von objekten und den
// spezies genauso wie in der vorhandenen edit maske!". One shape for
// both corrections, so the classes and the species read as the same kind
// of choice; the tile classes are defined once in 39-species-picker.css.
//
// COLOUR IS THE STATE. „Alle objekte sind bunt wenn angewählt und
// schwarz-weis / grautöne wenn nicht angewählt!" — an active class wears
// its own palette colour (core/icons.js::colors, the same one its badge,
// its lane and its box use everywhere else), an inactive one is greyed
// out. Nothing else marks the state: no ring, no border, no second cue.
function _classTileHtml(label, on) {
  const colour = colors[label] || colors.motion || '#93c5fd';
  return (
    `<button type="button" class="sp-pick-tile${on ? ' is-on' : ''}" ` +
    `data-label="${esc(label)}" aria-pressed="${on ? 'true' : 'false'}" ` +
    `style="--cb:${esc(colour)}">` +
    `<span class="sp-pick-bubble">${objIconSvg(label, 30)}</span>` +
    `<span class="sp-pick-name">${esc(OBJ_LABEL[label] || label)}</span></button>`
  );
}

function _sheetHtml(active) {
  const set = new Set(active || []);
  const tiles = _CHOICES.map((c) => _classTileHtml(c, set.has(c))).join('');
  return (
    // The sheet edits the CLIP's label set, not the row it was opened
    // from — POST …/events/<id>/labels has no per-detection form and the
    // ledger is keyed by event. The title says so, because a sheet
    // headed "Erkennung korrigieren" reads as a promise to change one
    // row out of four and would quietly break it for the others.
    `<div class="vp-sheet-title">Erkennungen dieser Aufnahme</div>` +
    // One toggle = one POST, already saved by the time the chip flips.
    // Said out loud because the operator could not tell: „muss ich
    // speichern oder fertig drücken damits übernommen wird?!"
    `<div class="vp-sheet-hint">Jede Änderung wird sofort gespeichert.</div>` +
    `<div class="sp-pick-grid">${tiles}</div>` +
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
 * @param {object} deps  { request, onSaved(result), onError, onClosed }
 *   `onClosed` fires once the sheet is off the page — the caller holds
 *   back the row-list repaint while it is open (a repaint would remove
 *   this element, which is a child of a row) and needs to know when it
 *   may catch up.
 * @returns {{teardown: () => void}|null}
 */
export function openReclassify(host, item, deps = {}) {
  if (!host || !item) return null;
  let labels = Array.isArray(item.labels) ? [...item.labels] : [];

  const sheet = document.createElement('div');
  sheet.className = 'vp-sheet';
  sheet.innerHTML = _sheetHtml(labels);
  host.appendChild(sheet);

  // Plain removal. `onClosed` is NOT fired here: the two programmatic
  // callers (opening a second sheet, tearing the whole panel down) are
  // the owner itself, which already knows — and firing it there would
  // repaint the row list out from under the sheet about to be opened on
  // one of its rows. Only the operator's own "Fertig" announces a close.
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
    else if (act === 'close') {
      close();
      deps.onClosed?.();
    }
  };
  sheet.addEventListener('click', onClick);

  return {
    teardown: () => {
      sheet.removeEventListener('click', onClick);
      close();
    },
  };
}
