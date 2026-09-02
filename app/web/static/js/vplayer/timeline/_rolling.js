// ─── vplayer/timeline/_rolling.js ──────────────────────────────────────────
// The live strip: the last 60 seconds, right-anchored, with new
// detections flowing in at the right edge.
//
// THREE BEHAVIOURS CARRIED OVER, each of which a rewrite drops easily
// because nothing else in the code references them:
//
//   1. THE FILTERED FOLD, with its "one pass makes it real" rule. A
//      lane counts as filtered only when EVERY sample in the window was
//      filtered — a track that passed even once is a real track having
//      a bad frame, not noise. Filtered lanes are segregated and
//      collapsed by default with a count on the toggle, so the
//      information stays one tap away without competing for the same
//      pixels.
//
//   2. THE FOLD'S PERSISTENCE, under the key the existing swimlane
//      already uses, so an operator who opened the fold finds it open.
//      Every access in try/catch: private mode throws on plain property
//      access and a strip that cannot render because a preference threw
//      is a worse failure than a forgotten fold.
//
//   3. THE LANE-STRUCTURE FINGERPRINT. The strip re-renders on every
//      tick. Rebuilding the DOM each time destroys and recreates every
//      bar, which on a phone is visible as a flicker and throws away any
//      in-progress interaction. The structure is rebuilt ONLY when lane
//      membership, colour or the fold state actually changes; otherwise
//      the existing bars are updated in place.

import { esc } from '../../core/dom.js';
import { lanesHtml } from './_lanes.js';

/** The existing swimlane's key — deliberately shared, not forked. */
const FILTERED_KEY = 'tam.ld.swim.filtered';

/** Read the fold state. Defaults to the calm state on any failure. */
export function loadShowFiltered() {
  try {
    return localStorage.getItem(FILTERED_KEY) === '1';
  } catch {
    return false;
  }
}

function _saveShowFiltered(on) {
  try {
    localStorage.setItem(FILTERED_KEY, on ? '1' : '0');
  } catch {
    /* private mode / quota — the session-local flag still works */
  }
}

/**
 * PURE: split lanes into the real ones and the wholly-filtered ones.
 *
 * A lane is filtered only when every sample in the window was — one
 * pass makes it a real track.
 */
export function splitFiltered(lanes) {
  const active = [];
  const filtered = [];
  for (const lane of lanes) {
    const segs = lane.segments || [];
    const isFiltered = segs.length > 0 && segs.every((s) => s.status === 'masked');
    (isFiltered ? filtered : active).push(lane);
  }
  return { active, filtered };
}

/**
 * PURE: the fingerprint of a rendered structure. Changes only when
 * something that requires a rebuild changed.
 */
export function laneFingerprint(lanes, showFiltered, filteredCount) {
  return (
    `${showFiltered ? 1 : 0}/${filteredCount}|` +
    lanes.map((l) => `${l.trackNum}:${l.colour}:${l.status}`).join('|')
  );
}

function _toggleHtml(count, open) {
  if (!count) return '';
  return (
    `<button type="button" class="vp-tl-filtered" data-action="vp-filtered" ` +
    `aria-expanded="${open ? 'true' : 'false'}">` +
    `${open ? 'Gefilterte ausblenden' : `Gefilterte anzeigen (${esc(String(count))})`}</button>`
  );
}

/**
 * Render (or update) the rolling strip.
 *
 * @param {HTMLElement} host
 * @param {object} model    from buildTimelineModel with windowMs set
 * @param {object} [opts]   { onToggle } — called after the fold flips
 */
export function renderRolling(host, model, opts = {}) {
  if (!host) return;
  const showFiltered = loadShowFiltered();
  const { active, filtered } = splitFiltered(model.lanes);
  const lanes = showFiltered ? active.concat(filtered) : active;
  const fp = laneFingerprint(lanes, showFiltered, filtered.length);
  if (host.dataset.vpFp === fp) return;

  host.innerHTML =
    `<div class="vp-tl-lanes">${lanesHtml({ ...model, lanes })}</div>` +
    _toggleHtml(filtered.length, showFiltered);
  host.dataset.vpFp = fp;

  host.querySelector('[data-action="vp-filtered"]')?.addEventListener('click', (ev) => {
    ev.stopPropagation();
    _saveShowFiltered(!showFiltered);
    // Re-render through the public entry so the fold state and the lane
    // structure can never drift apart.
    host.dataset.vpFp = '';
    renderRolling(host, model, opts);
    opts.onToggle?.(!showFiltered);
  });
}
