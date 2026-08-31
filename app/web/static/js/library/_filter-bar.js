// ─── library/_filter-bar.js ─────────────────────────────────────────────
// Stage 6 of the Mediathek + Wetter-Ereignisse merge: the one filter bar
// for the merged grid — camera chips, an object-class chip row (motion
// items only) and a weather-category chip row (sighting/manual/episode
// items only). Each toggle maps straight onto one `/api/library` query
// param; see `_filter-state.js::libraryQueryParams` for the exact
// mapping (split out there — pure, no DOM, no mediathek/filters.js
// import — so it stays importable without pulling in the whole
// Mediathek module graph this file's `MEDIA_FILTER_LABELS` import does).
//
// No per-option counts, unlike the two per-domain pill bars this
// replaces (`mediathek/filters.js::renderMediaFilterPills`,
// `weather/sightings.js`'s old `_renderWeatherFilterPills`): both read
// counts off a stats endpoint of their OWN domain
// (`/api/media/storage-stats`, `/api/weather/sightings`'s `counts`).
// `/api/library` has no cross-kind aggregate-count endpoint — adding
// one just to badge a chip is out of scope for wiring the existing
// building blocks up.
import { byId, esc } from '../core/dom.js';
import { state } from '../core/state.js';
import { getCameraIcon, getCameraColor, objIconSvg, OBJ_LABEL } from '../core/icons.js';
import { CAT_COLORS } from '../timeline.js';
import { MEDIA_FILTER_LABELS } from '../mediathek/filters.js';
import { WEATHER_TYPES } from '../core/weather-types.js';

export { createLibraryFilterState, libraryQueryParams } from './_filter-state.js';

// 'timelapse' is a `kind`, not an object label `/api/library`'s
// `label`/`labels` params can filter on (they only ever reach
// `motion_candidates`, see `library._feed._windowed_candidates`) — drop
// it from the reused Mediathek vocabulary rather than sending a filter
// value the backend would silently never match.
const _OBJECT_LABELS = MEDIA_FILTER_LABELS.filter((l) => l !== 'timelapse');

function _chip(group, val, active, iconHtml, label, color) {
  const cls = `media-pill cat-filter-btn${active ? ' active' : ''}`;
  return `<button type="button" class="${cls}" data-group="${group}" data-val="${esc(val)}" style="--cb:${color}"><span class="cfb-icon" style="pointer-events:none">${iconHtml}</span><span style="pointer-events:none">${esc(label)}</span></button>`;
}

function _cameraChipsHTML(filter) {
  return (state.cameras || [])
    .map((c) => {
      const active = filter.cameraIds.has(c.id);
      return _chip(
        'camera',
        c.id,
        active,
        getCameraIcon(c.name || c.id),
        c.name || c.id,
        getCameraColor(c),
      );
    })
    .join('');
}

function _labelChipsHTML(filter) {
  return _OBJECT_LABELS
    .map((l) => {
      const active = filter.labels.has(l);
      return _chip(
        'label',
        l,
        active,
        objIconSvg(l, 14),
        OBJ_LABEL[l] || l,
        CAT_COLORS[l] || '#94a3b8',
      );
    })
    .join('');
}

function _categoryChipsHTML(filter) {
  return Object.keys(WEATHER_TYPES)
    .map((k) => {
      const meta = WEATHER_TYPES[k];
      const active = filter.categories.has(k);
      return _chip('category', k, active, meta.icon, meta.de, meta.color);
    })
    .join('');
}

/** Paint the bar into #libraryFilterBar and wire every chip's toggle. */
export function renderLibraryFilterBar(filter, onChange) {
  const bar = byId('libraryFilterBar');
  if (!bar) return;
  // .media-filter-bar (reused, not reinvented) already carries the
  // flex-wrap row layout AND 25-mobile.css's horizontal-scroll-snap
  // treatment for exactly this "one row of .media-pill chips" shape —
  // see 26-library-merge.css's #libraryFilterBar comment.
  bar.innerHTML =
    `<div class="media-filter-bar" data-group="camera">${_cameraChipsHTML(filter)}</div>` +
    `<div class="media-filter-bar" data-group="label">${_labelChipsHTML(filter)}</div>` +
    `<div class="media-filter-bar" data-group="category">${_categoryChipsHTML(filter)}</div>`;
  bar.querySelectorAll('.media-pill').forEach((p) => {
    p.addEventListener('click', () => {
      const group = p.dataset.group;
      const val = p.dataset.val;
      const set =
        group === 'camera'
          ? filter.cameraIds
          : group === 'label'
            ? filter.labels
            : filter.categories;
      if (set.has(val)) set.delete(val);
      else set.add(val);
      onChange();
    });
  });
}
