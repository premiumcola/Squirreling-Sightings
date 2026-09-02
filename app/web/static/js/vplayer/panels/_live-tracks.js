// ─── vplayer/panels/_live-tracks.js ────────────────────────────────────────
// The live / simulation panel: what the pipeline is doing right now.
//
// Header carries the facts that change how every row below should be
// read — which mode ran this tick, whether it ran on the TPU or the
// CPU, and how much headroom the accelerator has left. A busy ratio
// near 1.0 explains a slow cadence, and without it the operator is left
// guessing whether the camera or the box is the problem.
//
// Then the active tracks, then two folds: the raw detections and the
// debug log. Both folds carry their own storage key, so opening one
// does not open the others.

import { esc } from '../../core/dom.js';
import { OBJ_LABEL } from '../../core/icons.js';
import { liveTrackColor } from '../../core/track-color.js';
import { PLACEHOLDER } from '../_helpers.js';
import { renderDebugLog } from './_debug-log.js';
import { renderRawDetections } from './_raw-detections.js';
import { computeChip, tpuBusyLabel, tpuFor, trackRow } from './_helpers.js';

/** German for the tracker's own state vocabulary. */
const _STATE_DE = {
  active: 'aktiv',
  coasting: 'überbrückt',
  closed: 'beendet',
};

function _chipsHtml(cfg, frame, status) {
  const modes = frame?.raw?.modes || null;
  const roi = modes?.roi_mode_active || modes?.roi_mode;
  const busy = tpuBusyLabel(tpuFor(status, cfg.item.camera_id));
  return (
    `<div class="vp-pnl-chips">` +
    `<span class="vp-pnl-chip">${esc(computeChip(modes))}</span>` +
    `<span class="vp-pnl-chip">ROI ${esc(roi || PLACEHOLDER)}</span>` +
    `<span class="vp-pnl-chip">TPU ${esc(busy)}</span>` +
    `</div>`
  );
}

function _trackHtml(t) {
  const r = trackRow(t);
  const cls = r.label ? OBJ_LABEL[r.label] || r.label : '—';
  const colour = r.num == null ? 'var(--muted)' : liveTrackColor(r.num);
  return (
    `<div class="vp-pnl-row" data-state="${esc(r.state)}" ` +
    `style="--vp-lane-colour:${esc(colour)}">` +
    `<span class="vp-pnl-num">${r.num == null ? '—' : `#${esc(String(r.num))}`}</span>` +
    `<span class="vp-pnl-cls">${esc(cls)}</span>` +
    `<span class="vp-pnl-score">${esc(r.score)}</span>` +
    `<span class="vp-pnl-reason">${esc(_STATE_DE[r.state] || r.state)} · Alter ${esc(r.age)}` +
    ` · Aussetzer ${esc(r.misses)} · IoU ${esc(r.iou)} · ${esc(r.model)}</span>` +
    `</div>`
  );
}

function _tracksHtml(frame) {
  // Track state rides the debug block, which the poll loop only
  // requests with ?debug=1. Without it there is nothing to list, and
  // saying so beats an empty box that looks broken.
  const tracks = frame?.raw?.debug?.tracks;
  if (!Array.isArray(tracks)) {
    return `<div class="vp-pnl-empty">Spur-Details brauchen den Debug-Modus</div>`;
  }
  if (!tracks.length) return `<div class="vp-pnl-empty">Keine aktiven Spuren</div>`;
  return tracks.map(_trackHtml).join('');
}

/**
 * Render the live / simulation panel.
 *
 * @param {HTMLElement} host
 * @param {object} cfg          normalised config from _config.js
 * @param {object} [frame]      latest mapped frame from _data/_map.js
 * @returns {{update, teardown}|null}
 */
export function renderLiveTracks(host, cfg, frame = null) {
  if (!host) return null;
  host.innerHTML =
    `<div class="vp-pnl-head"></div>` +
    `<div class="vp-pnl-tracks"></div>` +
    `<div class="vp-pnl-raw"></div>` +
    `<div class="vp-pnl-debug"></div>`;

  const head = host.querySelector('.vp-pnl-head');
  const tracks = host.querySelector('.vp-pnl-tracks');
  const raw = renderRawDetections(host.querySelector('.vp-pnl-raw'), cfg);
  const log = renderDebugLog(host.querySelector('.vp-pnl-debug'), cfg);

  const update = (f, status) => {
    head.innerHTML = _chipsHtml(cfg, f, status);
    tracks.innerHTML = _tracksHtml(f);
    raw?.update(f);
    log?.update(f?.trace || []);
  };
  update(frame, null);

  return {
    update,
    teardown: () => {
      raw?.teardown();
      log?.teardown();
      host.innerHTML = '';
    },
  };
}
