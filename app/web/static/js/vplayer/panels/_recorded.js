// ─── vplayer/panels/_recorded.js ───────────────────────────────────────────
// The recorded clip's panel: what was detected, and how the recording
// was made. Composition only — the rows come from _objects-list.js, the
// fold from _provenance.js, the correction sheet from _reclassify.js.

import { renderObjectsList } from './_objects-list.js';
import { renderProvenance } from './_provenance.js';
import { openReclassify } from './_reclassify.js';

/**
 * Render the recorded panel.
 *
 * @param {HTMLElement} host
 * @param {object} cfg   normalised config from _config.js
 * @param {object} deps  { request, tier, onDeleteObject, onSaved,
 *   onError }
 * @returns {{update, teardown}|null}
 */
export function renderRecordedPanel(host, cfg, deps = {}) {
  if (!host) return null;
  host.innerHTML = `<div class="vp-pnl-objects"></div><div class="vp-pnl-details"></div>`;

  let item = cfg.item;
  let models = null;
  let sheet = null;

  const objects = renderObjectsList(host.querySelector('.vp-pnl-objects'), {
    onEdit: (row, rowEl) => {
      sheet?.teardown();
      sheet = openReclassify(rowEl, item, {
        request: deps.request,
        onSaved: deps.onSaved,
        onError: deps.onError,
      });
    },
    onDelete: (row) => deps.onDeleteObject?.(row, item),
  });

  const details = renderProvenance(host.querySelector('.vp-pnl-details'), {
    tier: deps.tier,
    request: deps.request,
    onError: deps.onError,
  });

  return {
    update: (data) => {
      item = data?.item || item;
      models = data?.provenance?.models || null;
      objects?.update(data?.rows || [], models, data?.note || null);
      details?.update(item);
    },
    teardown: () => {
      sheet?.teardown();
      objects?.teardown();
      details?.teardown();
      host.innerHTML = '';
    },
  };
}
