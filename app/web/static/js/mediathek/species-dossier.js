// ─── mediathek/species-dossier.js ───────────────────────────────────────
// Per-species reference panel at the bottom of the Mediathek section
// (F08 follow-up — operator ask 2026-08-31: "Vogeldossier unten in die
// Mediathek einfügen, links das Dossier, rechts die Videos"). Left
// column: a compact reference card for one unlocked species (Wikipedia
// photo + a play-button affordance for its xeno-canto call, species
// name/latin, sighting-tier badge) plus a switcher over every unlocked
// species. Right column: the operator's OWN camera clips of that exact
// species via GET /api/library?labels=<German name>&kinds=motion — the
// same query param mediathek/_overview.js's "Tiere" quick tile and
// library/_filter-bar.js's object-class chips already send. No second
// media-fetch path, no second card renderer, per CLAUDE.md.
//
// Deliberately does NOT re-render the audio player + license
// attribution itself: bird_dossiers.py's module docstring makes
// attribution display next to the player mandatory (CC-BY compliance),
// and birds.js::openBirdDossier already renders that correctly,
// including the diversity-picked multi-clip list. Clicking the
// reference photo (or its play badge) opens that existing modal rather
// than duplicating the accredited player here.
//
// Data comes from birds.js's already-fetched dossier list —
// renderSpeciesDossierPanel(dossiers) is called once at the end of
// loadBirdDossiers(), not from a second /api/bird-dossiers fetch.
import { byId, esc } from '../core/dom.js';
import { apiGet } from '../core/api.js';
import { renderLibraryGrid } from '../library/_grid.js';
import { bindLibraryGrid } from '../library/_bind.js';
import { _achTier } from '../sichtungen.js';

// Same play-triangle path already inlined in storms/_footage.js and
// weather/_feed.js / _episode-footage-card.js — kept as a local literal
// per those files' own documented convention (no shared constant
// across packages for this one glyph).
const _PLAY_ICON =
  '<svg viewBox="0 0 24 24" width="30" height="30" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>';

const _CLIPS_LIMIT = 8;
const _TIER_LABEL = { bronze: 'Bronze', silver: 'Silber', gold: 'Gold' };

let _dossiers = [];
let _selectedLatin = null;

function _tierBadgeHtml(count) {
  const tier = _achTier(count);
  if (tier === 'locked') return '';
  return `<span class="species-dossier-tier-badge ${tier}">${_TIER_LABEL[tier]}</span>`;
}

function _heroHtml(d) {
  const src = d.wikipedia_thumb_url || '';
  const img = src
    ? `<img src="${esc(src)}" alt="" loading="lazy"/>`
    : '<div class="species-dossier-hero-placeholder">🐦</div>';
  const playable = (Array.isArray(d.recordings) && d.recordings.length) || !!d.audio_url;
  const badge = playable ? `<span class="ws-card-play">${_PLAY_ICON}</span>` : '';
  const label = esc(d.common_name_de || d.latin);
  return `<div class="species-dossier-hero-wrap bird-modal-hero" id="speciesDossierHero"
      role="button" tabindex="0" aria-label="Dossier zu ${label} öffnen">${img}${badge}</div>`;
}

function _switcherHtml() {
  const opts = _dossiers
    .map((d) => {
      const sel = d.latin === _selectedLatin ? ' selected' : '';
      return `<option value="${esc(d.latin)}"${sel}>${esc(d.common_name_de || d.latin)}</option>`;
    })
    .join('');
  return `<div class="species-dossier-switcher">
      <button type="button" class="species-dossier-switch-btn" id="speciesDossierPrevBtn"
        aria-label="Vorherige Art">‹</button>
      <select class="species-dossier-select" id="speciesDossierSelect"
        aria-label="Art wählen">${opts}</select>
      <button type="button" class="species-dossier-switch-btn" id="speciesDossierNextBtn"
        aria-label="Nächste Art">›</button>
    </div>`;
}

function _cardHtml(d) {
  const count = d.sighting_count || 1;
  return `${_heroHtml(d)}
    <div class="species-dossier-name">${esc(d.common_name_de || d.latin)}</div>
    <div class="species-dossier-latin">${esc(d.latin)}</div>
    <div class="species-dossier-meta">
      ${_tierBadgeHtml(count)}
      <span class="species-dossier-count">${count}× gesehen</span>
    </div>
    ${_switcherHtml()}`;
}

function _cycle(offset) {
  const idx = _dossiers.findIndex((x) => x.latin === _selectedLatin);
  if (idx < 0 || !_dossiers.length) return;
  const next = _dossiers[(idx + offset + _dossiers.length) % _dossiers.length];
  _selectSpecies(next.latin);
}

function _wireCard(d) {
  const hero = byId('speciesDossierHero');
  hero?.addEventListener('click', () => window.openBirdDossier?.(d.latin));
  hero?.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    e.preventDefault();
    window.openBirdDossier?.(d.latin);
  });
  byId('speciesDossierPrevBtn')?.addEventListener('click', () => _cycle(-1));
  byId('speciesDossierNextBtn')?.addEventListener('click', () => _cycle(1));
  byId('speciesDossierSelect')?.addEventListener('change', (e) => _selectSpecies(e.target.value));
}

function _wireViewAll(name) {
  const btn = byId('speciesDossierViewAllBtn');
  if (!btn) return;
  btn.style.display = name ? '' : 'none';
  btn.onclick = () => {
    if (name) window.setLibraryLabelFilter?.([name]);
  };
}

async function _loadClips(d) {
  const grid = byId('speciesDossierGrid');
  const title = byId('speciesDossierClipsTitle');
  const name = d.common_name_de || '';
  if (title) title.textContent = `Eigene Aufnahmen — ${d.common_name_de || d.latin}`;
  _wireViewAll(name);
  if (!grid) return;
  if (!name) {
    grid.innerHTML =
      '<div class="species-dossier-empty">Kein deutscher Artname hinterlegt — keine Zuordnung zur Mediathek möglich.</div>';
    return;
  }
  grid.innerHTML = '<div class="species-dossier-empty">Lade Aufnahmen…</div>';
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
    grid.innerHTML =
      '<div class="species-dossier-empty">Noch keine eigenen Aufnahmen dieser Art.</div>';
    return;
  }
  renderLibraryGrid(grid, items);
  bindLibraryGrid(grid, items);
}

function _render(d) {
  const card = byId('speciesDossierCard');
  if (!card || !d) return;
  card.innerHTML = _cardHtml(d);
  _wireCard(d);
  _loadClips(d);
}

function _selectSpecies(latin) {
  const d = _dossiers.find((x) => x.latin === latin);
  if (!d) return;
  _selectedLatin = latin;
  _render(d);
}

/** Boot / refresh entry — called from birds.js::loadBirdDossiers() with
 * the same /api/bird-dossiers payload that section already fetched.
 * Newest-first (list_dossiers()'s own order), so the freshest discovery
 * is the default selection. Re-renders in place on every call; the
 * previously-picked species stays selected across a refresh when it's
 * still in the list. */
export function renderSpeciesDossierPanel(dossiers) {
  _dossiers = Array.isArray(dossiers) ? dossiers : [];
  const panel = byId('speciesDossierPanel');
  if (!panel) return;
  if (!_dossiers.length) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  const stillPresent = _dossiers.some((d) => d.latin === _selectedLatin);
  _selectedLatin = stillPresent ? _selectedLatin : _dossiers[0].latin;
  _render(_dossiers.find((d) => d.latin === _selectedLatin));
}
