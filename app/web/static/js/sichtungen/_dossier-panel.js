// ─── sichtungen/_dossier-panel.js ────────────────────────────────────────
// The redesigned species dossier — replaces the old birds.js gallery
// (a grid of tiles that each opened a modal popup with a photo, latin
// name, sighting count and an X close button — "so eine hässliche Box
// mit X" per the operator). This panel is inline content that is simply
// THERE once any species has dossier data, never a popup: no X, no
// backdrop. Left column is the dossier itself — a hero photo that
// bleeds past its own card's padding (the "überlappend, ein bisschen
// größer" ask) with the species name + a play/chirp button burned
// straight into the photo (see _hero-overlay.js), the latin name/tier,
// the Wikipedia extract, and a compact list of Xeno-canto recordings
// with mandatory attribution. Right column is the operator's own
// camera clips of that species. There is no species switcher any
// more (2026-09 redesign) — a grid tile IS the species picker now, a
// second one inside the panel was redundant.
//
// Data flow is the one the deleted mediathek/species-dossier.js already
// worked out (git show 97b0dff): /api/bird-dossiers for the list, GET
// /api/library?labels=<name>&kinds=motion for the clips grid via
// library/_grid.js + library/_bind.js — no new media-fetch path, no new
// card renderer.
//
// Selection instead of open/close: a bird achievement tile (locked OR
// unlocked, see _achievements.js) calls selectSpeciesDossierByName to
// point this panel at that species. There is no "close" — the panel
// just shows whichever species was picked last. Unlike the deleted
// module, it shows NOTHING until a tile is actually tapped (2026-09
// fix — a still-locked, never-sighted species used to open itself on
// every page load just because it happened to be first in the list).
// That is the page's own established "no dismiss chrome" answer
// (mirrors _drilldown.js's second-click-closes convention isn't needed
// here because nothing is being popped open in the first place).
import { byId, esc } from '../core/dom.js';
import { apiGet, j } from '../core/api.js';
import { renderLibraryGrid } from '../library/_grid.js';
import { bindLibraryGrid } from '../library/_bind.js';
import { _achTier } from './_ach-defs.js';
import { heroHtml, audioListHtml, wireHeroAudio } from './_hero-overlay.js';

const _CLIPS_LIMIT = 8;
const _TIER_LABEL = { bronze: 'Bronze', silver: 'Silber', gold: 'Gold' };

let _dossiers = [];
let _nameToLatin = new Map();
let _selectedLatin = null;
// True once the first /api/bird-dossiers response has landed (success
// or failure) — distinguishes "still loading" from "loaded, but this
// species genuinely has no dossier yet" for selectSpeciesDossierByName
// below. A tile click that arrives before this flips shows an inline
// loading state instead of silently doing nothing (see the 2026-09
// dossier-panel fix: the old version raced loadAchievements() vs.
// loadBirdDossiers() in main.js — clicking a tile while the dossier
// fetch was still in flight looked up an empty _nameToLatin and no-oped
// with just a console.warn).
let _dossiersLoaded = false;
// A species name clicked before dossiers had loaded — resolved once
// loadBirdDossiers() finishes (see the end of that function).
let _pendingName = null;

function _normName(name) {
  return (name || '').trim().toLowerCase();
}

export function isSpeciesDossierActive(germanName) {
  if (!_selectedLatin) return false;
  return _nameToLatin.get(_normName(germanName)) === _selectedLatin;
}

export async function loadBirdDossiers() {
  try {
    const r = await j('/api/bird-dossiers');
    _dossiers = (r && r.dossiers) || [];
  } catch {
    _dossiers = [];
  }
  _nameToLatin = new Map(_dossiers.map((d) => [_normName(d.common_name_de), d.latin]));
  _dossiersLoaded = true;
  const panel = byId('speciesDossierPanel');
  if (!panel) return;
  // A tile was clicked while this fetch was still in flight — resolve
  // that click now instead of silently falling back to some default
  // species (the user asked for a specific one).
  if (_pendingName) {
    const name = _pendingName;
    _pendingName = null;
    selectSpeciesDossierByName(name);
    return;
  }
  if (!_dossiers.length) {
    panel.hidden = true;
    return;
  }
  // Collapsed by default — no species is auto-opened on load, only a
  // tile tap does that (selectSpeciesDossierByName below). A species
  // already open from an earlier click just gets its data refreshed in
  // place (e.g. a periodic re-poll), never a species that was never
  // clicked (the old "first dossier in the list opens itself" behaviour
  // showed a never-sighted Rotkehlchen expanded on every page load).
  if (_selectedLatin && _dossiers.some((d) => d.latin === _selectedLatin)) {
    _selectSpecies(_selectedLatin);
  }
}

// Bound to window — called from an achievement tile's inline onclick
// (see _achievements.js::_tileClickAttrs). Three cases:
//   1. dossiers already loaded + species found  → select it now.
//   2. dossiers not loaded yet (the /api/bird-dossiers fetch this page
//      load's loadBirdDossiers() kicked off — see main.js — is still in
//      flight, racing loadAchievements()'s tile render) → show an
//      inline loading state immediately and resolve once that fetch
//      lands (loadBirdDossiers() above checks _pendingName).
//   3. dossiers loaded but this species genuinely has none yet (the
//      daily prebuild sweep — bird_dossiers.py::sweep_prebuild — hasn't
//      reached it) → show an inline "not ready" state, not a silent
//      no-op.
export function selectSpeciesDossierByName(germanName) {
  const latin = _nameToLatin.get(_normName(germanName));
  if (latin) {
    _pendingName = null;
    _selectSpecies(latin);
    return;
  }
  if (!_dossiersLoaded) {
    _pendingName = germanName;
    _renderStateMessage(germanName, 'pending');
    return;
  }
  console.warn('[sichtungen] no dossier for', germanName);
  _renderStateMessage(germanName, 'missing');
}
window.selectSpeciesDossierByName = selectSpeciesDossierByName;

// Inline feedback for the two non-selection cases above — always
// visible (unhides the panel even if it was hidden for having zero
// dossiers overall), so a tile click always visibly does *something*.
// Never scrolls the page — the panel renders in place, below the grid,
// wherever the operator already is.
function _renderStateMessage(germanName, kind) {
  const panel = byId('speciesDossierPanel');
  if (!panel) return;
  panel.hidden = false;
  const name = esc(germanName || '');
  panel.innerHTML =
    kind === 'pending'
      ? `<div class="sd-state sd-state--pending">⏳ Dossier für <strong>${name}</strong> wird geladen …</div>`
      : `<div class="sd-state sd-state--missing">🕓 Für <strong>${name}</strong> ist noch kein Dossier vorbereitet — bitte später erneut versuchen.</div>`;
}

function _tierBadgeOrLockedHint(count) {
  const tier = _achTier(count);
  if (tier === 'locked') {
    return '<span class="sd-locked-hint">🔒 Noch nicht in deinem Garten gesichtet</span>';
  }
  return `<span class="sd-tier-badge ${tier}">${_TIER_LABEL[tier]}</span>`;
}

function _metaHtml(d) {
  const count = d.sighting_count || 0;
  // Small eyebrow label — the only remaining trace of the old standalone
  // "📖 Vogel-Dossiers" section heading, now living inside the panel
  // itself instead of a persistent header outside it (nothing to
  // duplicate: this panel IS the dossier, there's no second copy of the
  // label elsewhere on the page). The common (German) name itself now
  // lives burned into the hero photo (see _hero-overlay.js::heroHtml) —
  // not repeated here, that would be the exact duplication CLAUDE.md
  // forbids.
  return `<div class="sd-eyebrow">📖 Art-Dossier</div>
    <div class="sd-latin">${esc(d.latin)}</div>
    <div class="sd-badges">
      ${_tierBadgeOrLockedHint(count)}
      ${count > 0 ? `<span class="sd-count">${count}× gesehen</span>` : ''}
    </div>`;
}

function _wikiHtml(d) {
  if (d.wikipedia_summary) {
    return `<p class="sd-summary">${esc(d.wikipedia_summary)}</p>`;
  }
  return '<p class="sd-summary sd-summary--missing">Keine Wikipedia-Daten verfügbar — der nächste Abgleich versucht es erneut.</p>';
}

function _leftColumnHtml(d) {
  const wikiLink = d.wikipedia_url
    ? `<a class="sd-wiki-link" href="${esc(d.wikipedia_url)}" target="_blank" rel="noopener noreferrer">Auf Wikipedia ansehen ↗</a>`
    : '';
  return `<div class="sd-card">
    ${heroHtml(d)}
    ${_metaHtml(d)}
    ${_wikiHtml(d)}
    ${audioListHtml(d)}
    ${wikiLink}
  </div>`;
}

async function _loadClips(d) {
  const grid = byId('sdClipsGrid');
  const title = byId('sdClipsTitle');
  const name = d.common_name_de || '';
  if (title) title.textContent = `Eigene Aufnahmen — ${esc(d.common_name_de || d.latin)}`;
  if (!grid) return;
  if (!name) {
    grid.innerHTML =
      '<div class="sd-clips-empty">Kein deutscher Artname hinterlegt — keine Zuordnung zur Mediathek möglich.</div>';
    return;
  }
  grid.innerHTML = '<div class="sd-clips-empty">Lade Aufnahmen…</div>';
  let items = [];
  try {
    const r = await apiGet(
      `/api/library?labels=${encodeURIComponent(name)}&kinds=motion&limit=${_CLIPS_LIMIT}`,
    );
    items = (r && r.items) || [];
  } catch {
    items = [];
  }
  // The operator may have switched species while this fetch was in
  // flight — a stale response painting over the now-current selection
  // would look like the wrong species' clips.
  if (_selectedLatin !== d.latin) return;
  if (!items.length) {
    grid.innerHTML = '<div class="sd-clips-empty">Noch keine eigenen Aufnahmen dieser Art.</div>';
    return;
  }
  renderLibraryGrid(grid, items);
  bindLibraryGrid(grid, items);
}

function _renderPanel(d) {
  const panel = byId('speciesDossierPanel');
  if (!panel || !d) return;
  panel.innerHTML = `<div class="sd-grid">
    ${_leftColumnHtml(d)}
    <div class="sd-right">
      <div class="sd-clips-head">
        <span class="sd-clips-title" id="sdClipsTitle"></span>
      </div>
      <div class="sd-clips-grid" id="sdClipsGrid"></div>
    </div>
  </div>`;
  wireHeroAudio(panel);
  _loadClips(d);
}

// Never scrolls the page — the dossier renders in place below the grid
// (the operator's own "unangenehm runterspringen" complaint), whether
// this is the first-ever selection or a re-render of the open species.
function _selectSpecies(latin) {
  const d = _dossiers.find((x) => x.latin === latin);
  if (!d) return;
  _selectedLatin = latin;
  // The panel starts `hidden` in the template (nothing is open until a
  // tile is tapped, see loadBirdDossiers) — the first-ever selection has
  // to unhide it itself instead of relying on some earlier default-open.
  const panel = byId('speciesDossierPanel');
  if (panel) panel.hidden = false;
  _renderPanel(d);
}
