// ─── mediathek/filters.js ──────────────────────────────────────────────────
// R09.1 — extracted from orchestration.js. Filter pill bar bookkeeping +
// click handlers. Reads the active filter state from core/state and
// triggers a media-loader refresh on toggle. Click-time DOM updates
// delegate to renderMediaGrid + renderMediaPagination in
// orchestration.js — this module never owns the grid render itself.
import { byId } from '../core/dom.js';
import { state } from '../core/state.js';
import { OBJ_LABEL, objIconSvg } from '../core/icons.js';
import { CAT_COLORS } from '../timeline.js';
import { loadMedia } from './media-loader.js';
import { renderMediaGrid, renderMediaPagination } from './_paging.js';
import { openAllMediaDrilldown } from './_drilldown.js';
import { selectSpecies, speciesPillsHtml, clearSpeciesIfBirdInactive } from './_species-filter.js';
// Using a filter up HERE releases the Wetterdaten time chooser at the
// foot of the section — see weather/_time-binding.js for the rule.
import { noteFilterUse } from '../weather/_time-binding.js';

// ── Filter pill bar ─────────────────────────────────────────────────────────
// Sort happens at render time (by count desc); this list seeds the
// canonical set + tie-break order.
export const MEDIA_FILTER_LABELS = [
  'motion',
  'person',
  'cat',
  'bird',
  'car',
  'dog',
  'squirrel',
  'timelapse',
];

export function _aggregateMediaCounts() {
  const counts = {};
  MEDIA_FILTER_LABELS.forEach((l) => (counts[l] = 0));
  const stats = (state.mediaStats || []).filter((s) => {
    if (!state.mediaCamera) return true;
    return (s.camera_id || s.id || s.name) === state.mediaCamera;
  });
  stats.forEach((s) => {
    const lc = s.label_counts || {};
    Object.entries(lc).forEach(([k, v]) => {
      if (Object.prototype.hasOwnProperty.call(counts, k)) counts[k] += v || 0;
    });
    counts.timelapse += s.timelapse_count || 0;
  });
  return counts;
}

export function _seedTopMediaLabel() {
  // Seed-all-available: pre-select every label that actually has items
  // in the currently-aggregated counts. Tapping a pill DESELECTS it;
  // tapping again reselects. An empty Set is a UX shortcut for "no filter
  // active → show everything" — never an empty grid.
  // If state.mediaStats hasn't returned yet for the target cam (counts
  // are all zero), fall back to seeding the full canonical label set so
  // the pill bar shows "everything is active" right away. The downstream
  // filter is OR-of-labels, so a fully-seeded set behaves identically to
  // an empty set for the API call (both return everything) — but this
  // matches the user's mental model on the very first drilldown open.
  // _pruneEmptyMediaFilters() runs after loadMedia and trims any seeded
  // label that ended up with zero matches.
  const counts = _aggregateMediaCounts();
  const present = MEDIA_FILTER_LABELS.filter((l) => (counts[l] || 0) > 0);
  if (present.length > 0) {
    state.mediaLabels = new Set(present);
    return true;
  }
  state.mediaLabels = new Set(MEDIA_FILTER_LABELS);
  return false;
}

export function _pruneEmptyMediaFilters() {
  const counts = _aggregateMediaCounts();
  const before = state.mediaLabels.size;
  for (const l of [...state.mediaLabels]) {
    if (!counts[l]) state.mediaLabels.delete(l);
  }
  return before > 0 && state.mediaLabels.size === 0;
}

// One class-level pill's markup. L3 · render the SAME chips in both modes —
// categories with zero available items are surfaced as greyed/disabled
// (`media-pill--empty` + non-tappable), not removed entirely, so the
// operator sees the full taxonomy at a glance and knows what is/isn't
// available right now.
function _classPillHtml(l, cnt, mode) {
  const empty = cnt === 0;
  const active = mode === 'drilldown' && state.mediaLabels.has(l);
  const cls = `media-pill cat-filter-btn${active ? ' active' : ''}${empty ? ' media-pill--empty' : ''}`;
  const cb = CAT_COLORS[l] || '#94a3b8';
  const cntChip =
    mode === 'drilldown' && cnt > 0
      ? `<span class="mp-count" style="pointer-events:none">${cnt}</span>`
      : '';
  return `<button type="button" class="${cls}" data-type="label" data-val="${l}" style="--cb:${cb}"${empty ? ' tabindex="-1" aria-disabled="true"' : ''}><span class="cfb-icon" style="pointer-events:none">${objIconSvg(l, 18)}</span><span style="pointer-events:none">${OBJ_LABEL[l] || l}</span>${cntChip}</button>`;
}

// Click wiring for the class-level pills, split out of
// renderMediaFilterPills to keep that one under the file's own 60-line
// function ceiling.
function _wireClassPillClicks(bar, mode) {
  bar.querySelectorAll('.media-pill').forEach((p) => {
    if (p.classList.contains('media-pill--empty')) return;
    const val = p.dataset.val;
    // Belt-and-braces: re-set --cb via setProperty in addition to the
    // inline style attribute. The tinted-pill CSS reads var(--cb) for
    // the bg/text color-mix, and the drilldown bar inside .media-drill-
    // head was rendering as if --cb were missing on some browsers.
    if (val && CAT_COLORS[val]) p.style.setProperty('--cb', CAT_COLORS[val]);
    p.addEventListener('click', () => {
      if (mode === 'overview') {
        openAllMediaDrilldown(val);
        return;
      }
      noteFilterUse('label');
      if (state.mediaLabels.has(val)) state.mediaLabels.delete(val);
      else state.mediaLabels.add(val);
      // Deselecting "bird" (or any other pill, harmlessly) drops a
      // species narrowing that would otherwise keep filtering the grid
      // on a value the operator can no longer see or clear — see
      // _species-filter.js::clearSpeciesIfBirdInactive.
      clearSpeciesIfBirdInactive();
      state.mediaPage = 0;
      renderMediaFilterPills('drilldown');
      if (byId('mediaDrilldown')?.style.display !== 'none') {
        loadMedia().then(() => {
          renderMediaGrid();
          renderMediaPagination();
        });
      }
    });
  });
}

// Species sub-row lives in its own bar, below the class-level one (see
// partials/mediathek.html#mediaSpeciesFilterBar). No fetch of its own any
// more: it is derived from the same `state.mediaStats` this file's own
// `_aggregateMediaCounts` reads for the class pills, so both rows are one
// number from one source — see _species-filter.js's header.
function _syncSpeciesRow() {
  renderSpeciesFilterPills();
}

// mode: 'overview' (all pills, no counts, click → openAllMediaDrilldown(label))
//       'drilldown' (only pills with count>0, with counts, toggles state.mediaLabels)
export function renderMediaFilterPills(mode) {
  const id = mode === 'overview' ? 'mediaFilterBarOverview' : 'mediaFilterBar';
  const bar = byId(id);
  if (!bar) return;
  const counts = _aggregateMediaCounts();
  // Sort happens here (by count desc, MEDIA_FILTER_LABELS order as
  // tie-break) — recomputed from the same _aggregateMediaCounts() source
  // as the badge counts elsewhere (single source of truth); the
  // post-delete refresh in chrome/storage-stats.js re-fetches + re-renders.
  const labels = MEDIA_FILTER_LABELS.slice().sort((a, b) => {
    const d = (counts[b] || 0) - (counts[a] || 0);
    if (d) return d;
    return MEDIA_FILTER_LABELS.indexOf(a) - MEDIA_FILTER_LABELS.indexOf(b);
  });
  let html = labels.map((l) => _classPillHtml(l, counts[l] || 0, mode)).join('');
  // Status hint when the user has deselected every filter — the grid then
  // falls back to "show everything", and this pill keeps the state
  // visible so the user knows nothing is being hidden.
  if (mode === 'drilldown' && state.mediaLabels.size === 0 && labels.length > 0) {
    html += `<span class="media-pill media-pill--status" aria-disabled="true">alle Filter aus</span>`;
  }
  bar.innerHTML = html;
  _wireClassPillClicks(bar, mode);
  // 'overview' mode's pills are one-shot "jump into drilldown" shortcuts
  // (openAllMediaDrilldown above), not a live toggle — the species row
  // only means something once mediaLabels is actually driving a fetch.
  if (mode === 'drilldown') _syncSpeciesRow();
}

// Species pill row — separate render entry point from
// renderMediaFilterPills so a species click only repaints this one bar,
// not the whole class-level row above it.
export function renderSpeciesFilterPills() {
  const bar = byId('mediaSpeciesFilterBar');
  if (!bar) return;
  const html = speciesPillsHtml();
  bar.innerHTML = html;
  bar.hidden = !html;
  bar.querySelectorAll('.media-pill').forEach((p) => {
    const name = p.dataset.species;
    p.addEventListener('click', () => {
      noteFilterUse('species');
      selectSpecies(name);
      state.mediaPage = 0;
      renderSpeciesFilterPills();
      if (byId('mediaDrilldown')?.style.display !== 'none') {
        loadMedia().then(() => {
          renderMediaGrid();
          renderMediaPagination();
        });
      }
    });
  });
}

// Legacy alias — pills are now rendered dynamically via renderMediaFilterPills.
export function syncMediaPills() {
  renderMediaFilterPills('drilldown');
}
