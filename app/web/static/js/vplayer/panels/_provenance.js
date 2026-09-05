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

import { PLACEHOLDER } from '../../core/format.js';
import { esc } from '../../core/dom.js';
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
/**
 * PURE: the rows worth printing, and the sentence for the ones that
 * are not.
 *
 * ROWS WITH NOTHING IN THEM ARE DROPPED. „Was bringen unten die ganzen
 * Aufnahmedetails, wenn da überall nur 'n Strich ist, null oder null
 * Sekunden?" — on a clip older than the provenance snapshot that was
 * twelve of fifteen rows. A dash says "not recorded", which is worth
 * saying ONCE, in a sentence, rather than fifteen times in a table that
 * then buries the three values the clip does have.
 *
 * The sentence says WHY, which the dashes never did. The provenance
 * block is young — a clip recorded before it shipped has
 * `provenance: null` and can never gain one, so that is a fact about the
 * clip's age rather than a fault to chase. A clip that HAS a snapshot
 * but is missing the odd field gets the plain count instead: there the
 * gap is per-field and the age explanation would be wrong.
 *
 * @param {object} item
 * @returns {{rows: Array, note: string}}
 */
export function provenanceView(item) {
  const all = provenanceRows(item);
  const rows = all.filter((r) => r.value !== PLACEHOLDER);
  const missing = all.length - rows.length;
  if (!missing) return { rows, note: '' };
  const note = item?.provenance
    ? `${missing} weitere Angaben wurden für diesen Clip nicht aufgezeichnet.`
    : rows.length
      ? 'Ältere Aufnahme — für sie wurde noch kein Settings-Schnappschuss gespeichert.'
      : 'Für diesen Clip wurde kein Settings-Schnappschuss gespeichert.';
  return { rows, note };
}

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
    const view = provenanceView(item);
    rowsHost.innerHTML =
      kvRowsHtml(view.rows) +
      (view.note ? `<p class="vp-pnl-prov-gap">${esc(view.note)}</p>` : '');
  };

  paint(null);
  return {
    update: paint,
    teardown: () => fold.teardown(),
  };
}
