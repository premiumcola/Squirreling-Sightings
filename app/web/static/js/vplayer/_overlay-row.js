// ─── vplayer/_overlay-row.js ───────────────────────────────────────────────
// The overlay segmented control — Bboxes · Trails · Zonen · Masken —
// plus the ROI chip, in their own row below the stage.
//
// BELOW the stage, not pinned into a stage corner. The corner version
// is the layout that shipped a documented regression: two absolutely
// positioned clusters sharing one 390 px strip with no width budget,
// the right one measuring ~360 px on its own and sliding under the
// left, with its leading chips sheared off by the stage's
// overflow:hidden. A row in normal flow cannot collide with anything.
//
// PERSISTENCE IS NOT OURS. Every read and write goes through
// mediaview/overlay-toggles.js's getOverlayToggleState /
// setOverlayToggleState, against the same contextKey the pill bar uses
// ('mediathek' for recorded, 'live' for live and simulation). There is
// exactly one bucket: the Aufnahme-Settings panel's own bbox checkbox
// writes it too, so a second store here would silently reset an
// operator's preference depending on which surface they last used.
// Note zones and masks are declared persist:false there on purpose —
// setOverlayToggleState no-ops for them and they return to their
// default on the next open. That is the existing contract, not a bug.

import { esc } from '../core/dom.js';
import {
  _TOGGLES,
  _TOGGLE_ICONS,
  getOverlayToggleState,
  setOverlayToggleState,
} from '../mediaview/overlay-toggles.js';

function _segmentHtml(id, on) {
  const meta = _TOGGLES[id];
  if (!meta) return '';
  return (
    `<button type="button" class="vp-seg" data-layer="${esc(id)}" ` +
    `aria-pressed="${on ? 'true' : 'false'}" title="${esc(meta.desc || meta.label)}">` +
    `<span class="vp-seg-icon" aria-hidden="true">${_TOGGLE_ICONS[id] || ''}</span>` +
    `<span class="vp-seg-label">${esc(meta.label)}</span></button>`
  );
}

/**
 * The ROI chip. Read-only: it reports that detection ran on a crop
 * rather than the full frame, which is the single most common reason a
 * box "should have been found" and was not. Absent when there is no
 * ROI, because a chip reading "kein ROI" on every clip is noise.
 */
function _roiChipHtml(roi) {
  if (!roi) return '';
  return `<span class="vp-roi-chip" title="Erkennung lief auf einem Ausschnitt">ROI ${esc(roi)}</span>`;
}

/**
 * Mount the overlay row.
 *
 * @param {HTMLElement} host   the shell's [data-slot="toggles"]
 * @param {object} cfg         normalised config from _config.js
 * @param {object} [opts]
 * @param {string} [opts.roi]  ROI label, when the clip/session has one
 * @param {(state: object) => void} [opts.onChange]  full layer state
 * @returns {{state: () => object, teardown: () => void}|null}
 */
export function mountOverlayRow(host, cfg, opts = {}) {
  if (!host) return null;
  const ids = cfg.flags.overlayToggles;
  if (!ids.length) return null;

  const ctx = cfg.flags.contextKey;
  // Start from the caller's normalised overlays, but let a persisted
  // operator choice win for the layers that persist — the same
  // precedence the pill bar applies.
  const state = { ...cfg.overlays };
  for (const id of ids) {
    if (_TOGGLES[id]?.persist) state[id] = getOverlayToggleState(ctx, id);
  }

  host.innerHTML =
    `<div class="vp-segbar" role="group" aria-label="Overlays">` +
    ids.map((id) => _segmentHtml(id, state[id])).join('') +
    `</div>` +
    _hintHtml() +
    _roiChipHtml(opts.roi);

  const hint = host.querySelector('.vp-seg-hint');

  const apply = (id, on) => {
    state[id] = on;
    const btn = host.querySelector(`[data-layer="${id}"]`);
    btn?.setAttribute('aria-pressed', on ? 'true' : 'false');
    setOverlayToggleState(ctx, id, on);
    opts.onChange?.({ ...state });
  };

  const onClick = (ev) => {
    if (ev.target?.closest?.('.vp-seg-hint')) {
      apply('bboxes', true);
      return;
    }
    const btn = ev.target.closest?.('[data-layer]');
    if (!btn) return;
    apply(btn.dataset.layer, !state[btn.dataset.layer]);
  };
  host.addEventListener('click', onClick);

  return {
    state: () => ({ ...state }),
    /**
     * How many boxes this frame had and did not draw, from the painter.
     *
     * The whole point of the chip: the `bboxes` toggle persists across
     * every clip and every session, so one stray tap hides every box
     * from then on and the picture just looks like nothing was found.
     * A count is proof there IS something, and the chip hands it back in
     * one tap rather than sending the operator hunting for which of four
     * pills is the wrong colour.
     */
    setHiddenBoxes: (n) => {
      if (!hint) return;
      const show = n > 0;
      hint.hidden = !show;
      if (show) hint.textContent = `${n} Rahmen ausgeblendet — einblenden`;
    },
    teardown: () => {
      host.removeEventListener('click', onClick);
      host.innerHTML = '';
    },
  };
}

/** The "boxes are hidden" chip. Present but empty until the painter
 *  reports withheld boxes; a chip that renders on every clip would be
 *  the same noise the ROI chip is suppressed to avoid. */
function _hintHtml() {
  return `<button type="button" class="vp-seg-hint" hidden></button>`;
}
