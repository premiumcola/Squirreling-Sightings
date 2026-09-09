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
// DATA SOURCE: `state.mediaStats` — the per-camera stats the Mediathek
// has already fetched for the class-level pills above this row (see
// chrome/storage-stats.js and filters.js::_aggregateMediaCounts). Each
// camera carries a `species_counts` map, built by
// `media_index/_visible.py::camera_stats` from the very list of events
// the grid renders.
//
// IT USED TO READ GET /api/bird-dossiers' `sighting_count`, and that is
// the whole of „Ich wähle Filter Kohlmeise mit (1) und erhalte 31 Seiten
// andere Vögel". The dossier counts LIFETIME sightings and is never
// pruned; this row sits on a control that filters the ARCHIVE, which
// retention does prune. The two numbers answer different questions and
// drift apart in both directions — a species whose clips have aged out
// still counts in the dossier, and a sighting the dossier missed is
// still a clip the filter finds. A count printed beside a filter has to
// be that filter's own answer, so it is now counted from the same
// events, matched on the same field (`bird_species`), as the fetch the
// pill triggers.
//
// It also inherits the camera scoping for free: the same
// `state.mediaCamera` rule the class pills use, where the dossier list
// was installation-wide however narrow the view.
import { state } from '../core/state.js';
import { esc } from '../core/dom.js';
import { objIconSvg } from '../core/icons.js';

/** Species with at least one clip in the currently-scoped view, ranked
 * most-clips first — derived, not fetched. `[]` while the stats have not
 * loaded, which renders no species row at all (same quiet degradation
 * the previous fetch-failure path had). */
export function birdSpeciesOptions() {
  const counts = {};
  for (const cam of state.mediaStats || []) {
    // Same scoping rule as filters.js::_aggregateMediaCounts — one
    // camera when one is selected, all of them otherwise.
    if (state.mediaCamera && (cam.camera_id || cam.id || cam.name) !== state.mediaCamera) continue;
    for (const [name, n] of Object.entries(cam.species_counts || {})) {
      if (name) counts[name] = (counts[name] || 0) + (n || 0);
    }
  }
  return Object.entries(counts)
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'de'))
    .map(([name, count]) => ({ name, count }));
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
  const options = birdSpeciesOptions();
  if (!options.length) return '';
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
