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

import { esc } from '../../core/dom.js';
import { renderFold } from '../../core/fold.js';
import { provenanceRows } from './_helpers.js';

/** Its own key, so this fold opens independently of the other two. */
const FOLD_KEY = 'tamspy.vplayer.fold.details';

function _rowsHtml(item) {
  return provenanceRows(item)
    .map(
      (r) =>
        `<div class="vp-pnl-kv"><span class="vp-pnl-k">${esc(r.key)}</span>` +
        `<span class="vp-pnl-v${r.tone ? ` is-${r.tone}` : ''}">${esc(r.value)}</span></div>`,
    )
    .join('');
}

/**
 * The two actions that re-run detection.
 *
 * "Neu erkennen" re-indexes THIS recording: the tracking worker reads
 * the clip again and rewrites its tracks.json sidecar, so the timeline,
 * the boxes and the object list all change. That is the one that
 * answers "the settings are better now, redo this clip".
 *
 * "Kamera simulieren" opens the live simulation for the camera this
 * clip came from, which is how you check the CURRENT settings against a
 * live frame before deciding whether re-detecting the archive is even
 * worth it. It runs against live frames, not against this recording —
 * the backend has no endpoint that replays a stored clip through the
 * pipeline, so this is deliberately the camera, not the event.
 */
function _actionsHtml() {
  return (
    `<div class="vp-pnl-debug-bar">` +
    `<button type="button" class="vp-pnl-btn" data-action="vp-reindex">Neu erkennen</button>` +
    `<button type="button" class="vp-pnl-btn" data-action="vp-sim">Kamera simulieren</button>` +
    `</div>`
  );
}

/**
 * Render the 'Aufnahme-Details' fold.
 *
 * @param {HTMLElement} host
 * @param {object} deps  { tier, onReindex, onSimulate }
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

  const paint = (item) => {
    fold.body.innerHTML = _rowsHtml(item) + _actionsHtml();
    const on = (sel, fn) => {
      const btn = fold.body.querySelector(sel);
      if (btn && typeof fn === 'function') btn.addEventListener('click', fn);
    };
    on('[data-action="vp-reindex"]', () => deps.onReindex?.(item));
    on('[data-action="vp-sim"]', () => deps.onSimulate?.(item));
  };

  paint(null);
  return {
    update: paint,
    teardown: () => fold.teardown(),
  };
}
