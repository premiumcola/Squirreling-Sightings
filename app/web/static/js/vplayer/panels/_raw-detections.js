// ─── vplayer/panels/_raw-detections.js ─────────────────────────────────────
// The 'Rohe Erkennungen' fold: EVERY detection the model returned this
// frame, including the ones the pipeline threw away, each with the
// reason it was discarded.
//
// This is its own file because it is the single thing a rewrite drops
// most easily. It is a re-home, not new logic — the data already exists
// and is rendered today as the VERWORFEN section — and it is the only
// answer to the question operators actually ask, which is never "what
// did it find" but "why did it NOT alert on the thing I can see".
//
// A discarded row is not an error. It is the pipeline working: a class
// outside the filter, a subject inside a mask, a box outside every
// zone, a score under the spawn threshold. Each of those needs a
// different fix, so each says which one it was.

import { esc } from '../../core/dom.js';
import { renderFold } from '../../core/fold.js';
import { OBJ_LABEL } from '../../core/icons.js';
import { pctLabel, valueOr } from '../_helpers.js';

/** Its own key, so this fold opens independently of the other two. */
const FOLD_KEY = 'tamspy.vplayer.fold.raw';

function _rowHtml(det) {
  const cls = det.label ? OBJ_LABEL[det.label] || det.label : '—';
  const num = det.trackNum == null ? '' : `<span class="vp-pnl-num">#${esc(String(det.trackNum))}</span>`;
  const reason = det.discarded
    ? `<span class="vp-pnl-reason">${esc(valueOr(det.reason))}</span>`
    : '';
  return (
    `<div class="vp-pnl-row" data-discarded="${det.discarded ? '1' : '0'}" ` +
    `data-verdict="${esc(det.verdict || '')}">` +
    `${num}<span class="vp-pnl-cls">${esc(cls)}</span>` +
    `<span class="vp-pnl-score">${esc(pctLabel(det.score))}</span>` +
    `${reason}</div>`
  );
}

/** PURE: the fold's subtitle — how many were kept, how many were not. */
export function rawSummary(frame) {
  const kept = frame?.kept?.length || 0;
  const dropped = frame?.discarded?.length || 0;
  return `${kept} übernommen · ${dropped} verworfen`;
}

function _bodyHtml(frame) {
  const all = frame?.detections || [];
  if (!all.length) {
    return `<div class="vp-pnl-empty">Keine Erkennungen in diesem Frame</div>`;
  }
  // Kept first, then discarded — the discarded block is the diagnostic
  // half and reads as a group rather than as scattered greyed rows.
  const kept = frame.kept.map(_rowHtml).join('');
  const dropped = frame.discarded.length
    ? `<div class="vp-pnl-subhead">Verworfen</div>${frame.discarded.map(_rowHtml).join('')}`
    : '';
  return kept + dropped;
}

/**
 * Render the raw-detections fold.
 *
 * @param {HTMLElement} host
 * @param {object} [deps]  { tier }
 * @returns {{update: (frame: object) => void, teardown: () => void}|null}
 */
export function renderRawDetections(host, deps = {}) {
  if (!host) return null;
  const fold = renderFold(host, {
    key: FOLD_KEY,
    title: 'Rohe Erkennungen',
    defaultOpen: false,
    tier: deps.tier,
    prefix: 'vp-fold',
  });
  if (!fold) return null;

  return {
    update: (frame) => {
      fold.setTitle(`Rohe Erkennungen · ${rawSummary(frame)}`);
      fold.body.innerHTML = _bodyHtml(frame);
    },
    teardown: () => fold.teardown(),
  };
}
