// ─── vplayer/panels/index.js ───────────────────────────────────────────────
// ONE panel, two contents.
//
// A recorded clip's panel answers "what is in this recording, and how
// was it made": the detected objects, and the provenance fold. A live
// or simulation panel answers "what is the pipeline doing right now":
// the active tracks, the raw detections including the ones it threw
// away, and the debug log.
//
// They are two CONTENTS in one panel rather than two panels, because
// everything around them — the fold behaviour, the row geometry, the
// 44 px targets, the safe-area padding — is the same problem, and the
// last architecture solved it twice and then had to fix it twice.
//
// Which content is chosen comes from the mode's `panel` flag in
// _config.js. Nothing here branches on the mode itself.

import { renderLiveTracks } from './_live-tracks.js';
import { renderRecordedPanel } from './_recorded.js';

/**
 * Render the context panel.
 *
 * @param {HTMLElement} host  the shell's [data-slot="panel"]
 * @param {object} cfg        normalised config from _config.js
 * @param {object} [data]     latest mapped frame (live) or event data
 * @returns {{update: (d: object) => void, teardown: () => void}|null}
 */
export function renderContextPanel(host, cfg, data = null, deps = {}) {
  if (!host || !cfg.flags.showPanel) return null;
  // `deps` goes to BOTH panels. It used to reach only the recorded one,
  // so the live panel's folds were built with no device tier and the
  // desktop "there is room, open it" default never applied to them.
  if (cfg.flags.panel === 'live') return renderLiveTracks(host, cfg, data, deps);
  return renderRecordedPanel(host, cfg, deps);
}
