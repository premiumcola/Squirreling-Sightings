// ─── vplayer/panels/_provenance.js ─────────────────────────────────────────
// The 'Aufnahme-Details' fold: how this recording was actually made.
//
// It answers the question that otherwise costs a log dive — "why did
// THIS clip come out like this" — from the settings snapshot the event
// was recorded under, rather than from the settings as they are now.
// Those two drift the moment anyone touches a threshold, and a panel
// that showed the current values would quietly lie about every clip
// older than the last edit.
//
// EVERY ROW DEGRADES INDEPENDENTLY. The provenance block is young: a
// clip from before it landed has `provenance: null`, and any recording
// whose snapshot threw has it too. panels/_helpers.js::provenanceRows
// owns that fallback chain — including the older, narrower
// recording_settings — and is the only place a field name appears.

import { renderFold } from '../../core/fold.js';
import { kvRowsHtml, provenanceRows } from './_helpers.js';

/** Its own key, so this fold opens independently of the other two. */
const FOLD_KEY = 'tamspy.vplayer.fold.details';

/**
 * Render the 'Aufnahme-Details' fold — the rows, and only the rows.
 *
 * The replay block used to live in here, under those rows. It is an
 * ACTION and they are a record, and burying an action inside a collapsed
 * fold beneath fifteen key/value lines is how it stopped being findable:
 * „bitte nehm die option weiter oben rein". It is now mounted by
 * _recorded.js directly beneath the object list, where the thing it
 * changes is visible.
 *
 * @param {HTMLElement} host
 * @param {object} deps  { tier }
 * @returns {{update: (item) => void, teardown: () => void}|null}
 */
export function renderProvenance(host, deps = {}) {
  if (!host) return null;
  const fold = renderFold(host, {
    key: FOLD_KEY,
    title: 'Aufnahme-Details',
    defaultOpen: false,
    tier: deps.tier,
    prefix: 'vp-fold',
  });
  if (!fold) return null;

  fold.body.innerHTML = `<div class="vp-pnl-prov-rows"></div>`;
  const rowsHost = fold.body.querySelector('.vp-pnl-prov-rows');

  const paint = (item) => {
    rowsHost.innerHTML = kvRowsHtml(provenanceRows(item));
  };

  paint(null);
  return {
    update: paint,
    teardown: () => fold.teardown(),
  };
}
