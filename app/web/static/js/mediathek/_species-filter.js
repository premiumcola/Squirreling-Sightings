// ─── mediathek/_species-filter.js ──────────────────────────────────────────
// The Mediathek's species sub-filter — a second row of pills, under the
// "Vogel" class pill, that narrows the grid to one bird species (e.g.
// "Elster") without leaving Mediathek for the separate Sichtungen tab.
//
// Kept as a leaf module deliberately: filters.js itself pulls in
// _paging.js and _drilldown.js, which reach lightbox.js — a module with
// real top-level DOM side effects (`byId('lightboxClose').onclick =
// ...`) that make anything importing it unimportable under the node
// --test stubs the rest of mediathek/_tests/ relies on. Everything here
// is state-mutation + pure HTML-string building + the one fetch, so it
// stays testable the same way _cards.js / _processing.js are: stub
// document/fetch, import, assert. filters.js does the DOM wiring
// (querySelector + addEventListener) that actually needs a real page.
//
// Data source: GET /api/bird-dossiers, filtered to sighting_count > 0.
// That endpoint already exists for the Sichtungen dossier panel and
// already hands out the exact value (`common_name_de`) this codebase
// uses as a `labels=` filter value elsewhere (see
// sichtungen/_dossier-panel.js's own clips-gallery fetch:
// `/api/library?labels=<name>&kinds=motion`) — so reusing it needs no
// new backend route and no new value shape to keep in sync.
//
// It is NOT scoped to the currently selected camera: bird-dossiers is
// installation-wide. The alternative, storage_stats.top_bird_species
// (via GET /api/camera/<id>/stats_range), IS camera-scoped but only
// per single camera — the Mediathek "Alle Kameras" view (the default
// drilldown, see _drilldown.js::openAllMediaDrilldown) has no camera id
// to call it with, and merging N per-camera Counters into one ranked
// list is a fan-out this codebase doesn't do anywhere yet. Given this
// is a small self-hosted install (a handful of cameras, a handful of
// species actually seen), the installation-wide list is close enough,
// and sighting_count > 0 already excludes every never-seen species the
// daily dossier prebuild sweep pre-creates as a locked placeholder (see
// bird_dossiers.py::sweep_prebuild) — this pill row only ever shows
// species the operator has actually had on camera.
import { state } from '../core/state.js';
import { esc } from '../core/dom.js';
import { objIconSvg } from '../core/icons.js';
import { j } from '../core/api.js';

let _optionsFetch = null;

/** Species actually sighted, ranked most-sighted first. Resets
 * state.mediaSpeciesOptions to `[]` on any fetch failure — same
 * fail-quiet contract loadBirdDossiers() in _dossier-panel.js uses, so
 * one flaky request degrades to "no species row" rather than an error
 * state atop the otherwise-working class-level filter bar. Concurrent
 * callers (renderMediaFilterPills firing on every re-render while the
 * first request is still in flight) share the one in-flight promise
 * instead of each starting their own fetch. */
export function loadBirdSpeciesOptions() {
  if (_optionsFetch) return _optionsFetch;
  // j(), not apiGet() — the same fetch helper _dossier-panel.js's own
  // loadBirdDossiers() already uses for this exact endpoint.
  _optionsFetch = j('/api/bird-dossiers')
    .then((r) => (r && r.dossiers) || [])
    .catch(() => [])
    .then((dossiers) => {
      state.mediaSpeciesOptions = dossiers
        .filter((d) => (d.sighting_count || 0) > 0 && d.common_name_de)
        .sort((a, b) => (b.sighting_count || 0) - (a.sighting_count || 0))
        .map((d) => ({ name: d.common_name_de, count: d.sighting_count || 0 }));
      return state.mediaSpeciesOptions;
    });
  return _optionsFetch;
}

// Toggle: selecting the already-selected species clears it — the same
// second-click-deselects convention the class-level pills
// (filters.js::renderMediaFilterPills) already use.
export function selectSpecies(name) {
  state.mediaSpecies = state.mediaSpecies === name ? null : name;
}

// Deselecting the "bird" class pill (or never having selected it) must
// drop any species narrowing along with it — a species pill with no
// visible "bird" pill above it would filter the grid on a value the
// operator can no longer see or clear. Safe to call after every
// class-pill toggle, not just bird's own: a no-op whenever "bird" is
// still active.
export function clearSpeciesIfBirdInactive() {
  if (!state.mediaLabels.has('bird')) state.mediaSpecies = null;
}

// The effective label list media-loader.js's loadMedia() sends as
// `label=`/`labels=`. A selected species is an EXCLUSIVE narrow, not one
// more value OR'd into the set: the backend filter (storage.py::
// _filter_events) only ever does OR-of-filter-set, with no AND — so
// `{"cat", "Elster"}` would not mean "Elster birds, plus any cat", it
// would mean "every cat event, UNION the Elster ones", which is a wider
// result than "cat" alone, not a narrower one. A sibling class pill
// (person, cat, ...) staying visibly "active" while a species is picked
// is cosmetic only; the fetch itself must drop them, or picking a rare
// species surfaces mostly unrelated person/cat cards sorted in ahead of
// it — exactly the "Vogelartenfilter funktionieren nicht" report this
// fixed (a species pick was OR-widening the result set instead of
// narrowing it whenever another class pill was still checked, which the
// default "seed every available class" behaviour makes the common case,
// not an edge case).
export function effectiveMediaLabels() {
  if (state.mediaSpecies) return [state.mediaSpecies];
  return [...state.mediaLabels];
}

// Pure HTML-string builder for the species pill row — empty string
// (never rendered / hidden) unless "bird" is the active class filter
// AND at least one species has actually been sighted. Mirrors
// renderMediaFilterPills' pill markup (same `media-pill cat-filter-btn`
// classes) so the two rows read as one family; `media-pill--species`
// is an extra hook with no CSS behaviour of its own today, for a
// callsite that wants to style the row without also matching the
// class-level pills.
export function speciesPillsHtml() {
  if (!state.mediaLabels.has('bird')) return '';
  const options = state.mediaSpeciesOptions;
  if (!options || !options.length) return '';
  return options
    .map(({ name, count }) => {
      const active = state.mediaSpecies === name;
      const cls = `media-pill cat-filter-btn media-pill--species${active ? ' active' : ''}`;
      return (
        `<button type="button" class="${cls}" data-species="${esc(name)}">` +
        `<span class="cfb-icon" style="pointer-events:none">${objIconSvg('bird', 16)}</span>` +
        `<span style="pointer-events:none">${esc(name)}</span>` +
        `<span class="mp-count" style="pointer-events:none">${count}</span></button>`
      );
    })
    .join('');
}
