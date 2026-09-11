// ─── mediathek/_species-filter.js ──────────────────────────────────────────
// The Mediathek's species sub-filter — the chips INSIDE the "Vogel" class
// pill that narrow the grid to one bird species (e.g. "Elster") without
// leaving Mediathek for the separate Sichtungen tab.
//
// They used to be a second row of pills under the class row, which read
// as a second taxonomy of equal rank next to Katze/Person/Hund rather
// than as what they are — a narrowing of ONE of those pills: „stelle die
// spezies als unterfilter zu vogel der indem die alle in eine art
// aufgeklappte bubble rein kommen als unterelemente zu Vogel!". So the
// pill opens into a bubble and holds them; see speciesNestHtml at the
// foot of this file.
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
import { speciesIconMarkup } from '../core/species-icon.js';

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

/** Clips carrying `name` in the currently-scoped view — the very number
 * that species' own pill prints, read back by name. filters.js needs it
 * to answer „wie viele Vögel" while a species is narrowing the grid: the
 * class row's own source (`label_counts`) only knows the whole archive's
 * bird total, which is the wrong number to print beside a filter that
 * has already been narrowed past it. */
export function speciesClipCount(name) {
  return birdSpeciesOptions().find((o) => o.name === name)?.count || 0;
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

// Pure HTML-string builder for the species chips — empty string unless
// "bird" is the active class filter AND at least one species has
// actually been sighted. Mirrors renderMediaFilterPills' pill markup
// (same `media-pill cat-filter-btn` classes) so pill and chip read as
// one family; `media-pill--species` is the hook that styles them as the
// bubble's children without also matching the class-level pills.
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
        // THE SPECIES' OWN SILHOUETTE, not the generic bird glyph — the
        // same drawing its tiles, its picker bubble and the achievement
        // board use („Icon der spezies auch im filter!"). A row of
        // identical bird outlines told the eye nothing; these are
        // distinguishable at a glance, which is the whole job of a
        // filter row you scroll sideways.
        `<span class="cfb-icon cfb-icon--species" style="pointer-events:none">` +
        `${speciesIconMarkup(name)}</span>` +
        `<span style="pointer-events:none">${esc(name)}</span>` +
        `<span class="mp-count" style="pointer-events:none">${count}</span></button>`
      );
    })
    .join('');
}

// ── The bubble ──────────────────────────────────────────────────────────

/** Is there anything to nest under "Vogel" at all? False on an
 * installation that has never had a determined species on camera — the
 * pill then stays an ordinary pill, because an empty bubble is a control
 * that promises children it does not have. */
export function hasSpeciesToNest() {
  return birdSpeciesOptions().length > 0;
}

// OPEN IS NOT A STATE OF ITS OWN. The bubble stands open exactly while
// "bird" is the active class filter — the same condition that used to
// decide whether the separate species row was painted at all. So the tap
// the operator described („Vogel … beim aufklappen") is the tap that was
// always there, and no pill carries two meanings: activating Vogel opens
// it, deactivating Vogel closes it and drops the species narrowing with
// it (clearSpeciesIfBirdInactive, called from the same click handler).
export function speciesNestOpen() {
  return state.mediaLabels.has('bird') && hasSpeciesToNest();
}

/** The open bubble: the caller's own "Vogel" button as its head, the
 * species chips as its children — „Vogel wird beim aufklappen nur noch
 * das icon und hat die spezies drin!".
 *
 * `headHtml` is passed IN rather than built here: filters.js owns the
 * class-pill vocabulary (OBJ_LABEL, CAT_COLORS, objIconSvg) and there is
 * exactly one pill builder, so the head is the same button in the same
 * markup whether it stands alone or heads a bubble. The kids sit in a
 * plain `.media-filter-bar`, which is what gives them the sideways
 * scroll-snap strip on a phone (25-mobile.css) — a species list is
 * open-ended where the class taxonomy is eight words long.
 *
 * '' when the bubble is not open, so a caller can concatenate it
 * unconditionally. */
export function speciesNestHtml(headHtml) {
  if (!speciesNestOpen()) return '';
  return (
    `<div class="media-nest media-nest--species">${headHtml}` +
    `<div class="media-filter-bar media-nest-kids">${speciesPillsHtml()}</div></div>`
  );
}
