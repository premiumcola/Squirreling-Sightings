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
import { renderReplay } from './_replay.js';

/** Its own key, so this fold opens independently of the other two. */
const FOLD_KEY = 'tamspy.vplayer.fold.details';

/**
 * Render the 'Aufnahme-Details' fold.
 *
 * The rows say what this clip was recorded WITH; the replay block below
 * them (panels/_replay.js) is what turns that record into something you
 * can act on — re-running this very clip under the settings on record
 * or under the camera's current profile, and showing the difference
 * inline.
 *
 * The two halves get their own hosts because they repaint on different
 * clocks: the rows are rewritten on every `update`, while the replay
 * block owns a request in flight and must survive one.
 *
 * @param {HTMLElement} host
 * @param {object} deps  { tier, request, onError }
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

  fold.body.innerHTML = `<div class="vp-pnl-prov-rows"></div><div class="vp-pnl-prov-replay"></div>`;
  const rowsHost = fold.body.querySelector('.vp-pnl-prov-rows');
  const replay = renderReplay(fold.body.querySelector('.vp-pnl-prov-replay'), {
    request: deps.request,
    onError: deps.onError,
  });

  const paint = (item) => {
    rowsHost.innerHTML = kvRowsHtml(provenanceRows(item));
    replay?.update(item);
  };

  paint(null);
  return {
    update: paint,
    teardown: () => {
      replay?.teardown();
      fold.teardown();
    },
  };
}
