// ─── vplayer/panels/_recorded.js ───────────────────────────────────────────
// The recorded clip's panel: what was detected, and how the recording
// was made. Composition only — the rows come from _objects-list.js, the
// fold from _provenance.js, the correction sheet from _reclassify.js.
//
// IT PAINTS FROM THE ITEM, NOT FROM A SNAPSHOT. Everything on screen is
// re-derived from the event object this panel currently holds, so there
// is exactly one way for the panel to change: change the item, then
// repaint. That is what makes a correction land — the sheet POSTs, the
// server answers with the fields it actually wrote, those fields go onto
// the item, and the panel is rebuilt from it. Nothing is patched into
// the DOM optimistically, so a save that failed cannot leave the panel
// showing a change the backend never made.
//
// THE ITEM IS PATCHED IN PLACE, deliberately. The correction sheet
// captured this same object by reference and re-reads `item.labels`
// every time it is opened. Replacing the object instead would leave the
// NEXT sheet rendering the label set from before the correction — the
// exact "I fixed it and it still shows the old one" this wiring closes.

import { applyLabelPatch } from '../../core/label-patch.js';
import { objectRowsFor, objectsNote } from '../_data/_map.js';
import { clipReadiness } from '../_model/readiness.js';
import { renderObjectsList } from './_objects-list.js';
import { renderProvenance } from './_provenance.js';
import { renderReadinessNote } from './_readiness-note.js';
import { openReclassify } from './_reclassify.js';
import { renderReplay } from './_replay.js';

/**
 * Rebuild both halves of the panel from the state bag.
 *
 * Lives at module scope so the composition below stays a composition.
 * `st` is mutable and read on every call on purpose — it is the one
 * place the panel's current item lives, and a captured copy would go
 * stale the first time a correction landed.
 *
 * @param {object|null} objects  the object-list handle
 * @param {object|null} details  the provenance-fold handle
 * @param {{item: object, tracks: object|null, models: object|null}} st
 * @param {{keepSheet?: boolean}} opts  `keepSheet` skips the row list —
 *   the correction sheet is mounted INSIDE a row, so rebuilding the list
 *   under it tears the open sheet off the page mid-edit. Every other
 *   part still repaints, and the list catches up when the sheet closes.
 */
function _paintPanel(parts, st, opts = {}) {
  if (!opts.keepSheet) {
    const rows = objectRowsFor(st.item, st.tracks);
    parts.objects?.update(rows, st.models, objectsNote(rows, st.item));
  }
  // `st.fetched` distinguishes "the sidecar request has not come back"
  // from "there is none" — collapsing those two is exactly what made an
  // empty picture unreadable.
  //
  // The ITEM travels with the verdict: the note's building face reads the
  // stage vocabulary and the seconds-in-stage off it, and `st.item` is
  // the only reference that survives both a correction (patched in place)
  // and a widening (replaced by loadRecorded).
  parts.note?.update(clipReadiness(st.item, st.fetched ? st.tracks : undefined), st.item);
  parts.replay?.update(st.item);
  parts.details?.update(st.item);
}

/**
 * Render the recorded panel.
 *
 * @param {HTMLElement} host
 * @param {object} cfg   normalised config from _config.js
 * @param {object} deps  { request, tier, onSaved, onError }
 * @returns {{update, teardown}|null}
 */
export function renderRecordedPanel(host, cfg, deps = {}) {
  if (!host) return null;
  // The readiness note sits ABOVE the rows: it says how much to trust
  // what follows, which is worthless underneath it.
  // Order is the argument. First why the picture looks like this, then
  // WHAT was detected, then the actions that change it, and only then the
  // record of how the clip was made. The replay used to sit last, inside
  // the collapsed fold and under fifteen rows.
  host.innerHTML =
    `<div class="vp-pnl-readiness"></div>` +
    `<div class="vp-pnl-objects"></div>` +
    `<div class="vp-pnl-replay"></div>` +
    `<div class="vp-pnl-details"></div>`;

  const st = { item: cfg.item, tracks: null, models: null, fetched: false };
  let sheet = null;

  const objects = renderObjectsList(host.querySelector('.vp-pnl-objects'), {
    onEdit: (row, rowEl) => {
      sheet?.teardown();
      sheet = openReclassify(rowEl, st.item, {
        request: deps.request,
        onSaved: saved,
        onError: deps.onError,
        // The list was skipped while the sheet was up (see _paintPanel's
        // `keepSheet`) — now that the sheet is gone it has to catch up,
        // or the row headings keep showing the pre-correction class.
        onClosed: () => {
          sheet = null;
          paint();
        },
      });
    },
  });

  const note = renderReadinessNote(host.querySelector('.vp-pnl-readiness'), cfg, {
    request: deps.request,
    onError: deps.onError,
  });

  const replay = renderReplay(host.querySelector('.vp-pnl-replay'), {
    request: deps.request,
    onError: deps.onError,
  });

  const details = renderProvenance(host.querySelector('.vp-pnl-details'), {
    tier: deps.tier,
  });

  const parts = { objects, note, replay, details };
  const paint = (opts) => _paintPanel(parts, st, opts);

  // A correction came back. The reply is authoritative — `top_label` is
  // the backend's own derivation and `bird_species` may just have been
  // cleared — so it lands on the item before anything repaints.
  // `deps.onSaved` runs LAST and is the outward half: the Mediathek's
  // caches, the grid card behind the player and the timeline counts all
  // still hold the old verdict until it does.
  const saved = (res, labels) => {
    applyLabelPatch(st.item, res);
    // Every tap in the sheet IS the save — one toggle, one POST (see
    // _reclassify.js's header). The repaint used to take the sheet down
    // with it on every one of them, which read as "it cancelled": „Nach
    // jeder Änderung schliesst sich das edit menü — muss ich speichern
    // oder fertig drücken damits übernommen wird?!". It stays up now,
    // and "Fertig" only closes it.
    paint({ keepSheet: !!sheet });
    deps.onSaved?.(res, labels);
  };

  return {
    update: (data) => {
      st.item = data?.item || st.item;
      st.tracks = data?.tracks || null;
      st.models = data?.provenance?.models || null;
      // loadRecorded has answered — whatever it found, including nothing.
      st.fetched = true;
      paint();
    },
    teardown: () => {
      sheet?.teardown();
      objects?.teardown();
      note?.teardown();
      replay?.teardown();
      details?.teardown();
      host.innerHTML = '';
    },
  };
}
