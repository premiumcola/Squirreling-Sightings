// ─── sichtungen/_dossier-panel.js ────────────────────────────────────────
// The redesigned species dossier — replaces the old birds.js gallery
// (a grid of tiles that each opened a modal popup with a photo, latin
// name, sighting count and an X close button — "so eine hässliche Box
// mit X" per the operator). This panel is inline content that is simply
// THERE once any species has dossier data, never a popup: no X, no
// backdrop. Left column is the dossier itself — a hero photo that
// bleeds past its own card's padding (the "überlappend, ein bisschen
// größer" ask), name/latin/tier, the Wikipedia extract, and the
// Xeno-canto audio player with mandatory attribution. Right column is
// the operator's own camera clips of that species.
//
// Data flow is the one the deleted mediathek/species-dossier.js already
// worked out (git show 97b0dff): /api/bird-dossiers for the list + a
// prev/next/select switcher, GET /api/library?labels=<name>&kinds=motion
// for the clips grid via library/_grid.js + library/_bind.js — no new
// media-fetch path, no new card renderer.
//
// Selection instead of open/close: a bird achievement tile (locked OR
// unlocked, see _achievements.js) calls selectSpeciesDossierByName to
// point this panel at that species and scroll it into view. There is no
// "close" — the panel just shows whichever species was picked last,
// exactly like the deleted module always showed *something* once data
// existed. That is the page's own established "no dismiss chrome"
// answer (mirrors _drilldown.js's second-click-closes convention isn't
// needed here because nothing is being popped open in the first place).
import { byId, esc } from '../core/dom.js';
import { apiGet, j } from '../core/api.js';
import { renderLibraryGrid } from '../library/_grid.js';
import { bindLibraryGrid } from '../library/_bind.js';
import { _achTier } from './_ach-defs.js';

const _CLIPS_LIMIT = 8;
const _TIER_LABEL = { bronze: 'Bronze', silver: 'Silber', gold: 'Gold' };

let _dossiers = [];
let _nameToLatin = new Map();
let _selectedLatin = null;

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
  const panel = byId('speciesDossierPanel');
  if (!panel) return;
  if (!_dossiers.length) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  const stillPresent = _dossiers.some((d) => d.latin === _selectedLatin);
  _selectSpecies(stillPresent ? _selectedLatin : _dossiers[0].latin, false);
}

// Bound to window — called from an achievement tile's inline onclick
// (see _achievements.js::_tileClickAttrs). No-ops quietly when the
// species has no dossier yet (e.g. the daily prebuild sweep hasn't
// reached it — see bird_dossiers.py::sweep_prebuild — so this stays a
// transitional gap, not a permanent dead end).
export function selectSpeciesDossierByName(germanName) {
  const latin = _nameToLatin.get(_normName(germanName));
  if (!latin) {
    console.warn('[sichtungen] no dossier yet for', germanName);
    return;
  }
  _selectSpecies(latin, true);
}
window.selectSpeciesDossierByName = selectSpeciesDossierByName;

function _cycle(offset) {
  const idx = _dossiers.findIndex((x) => x.latin === _selectedLatin);
  if (idx < 0 || !_dossiers.length) return;
  const next = _dossiers[(idx + offset + _dossiers.length) % _dossiers.length];
  _selectSpecies(next.latin, false);
}

function _tierBadgeOrLockedHint(count) {
  const tier = _achTier(count);
  if (tier === 'locked') {
    return '<span class="sd-locked-hint">🔒 Noch nicht in deinem Garten gesichtet</span>';
  }
  return `<span class="sd-tier-badge ${tier}">${_TIER_LABEL[tier]}</span>`;
}

function _heroHtml(d) {
  const src = d.wikipedia_thumb_url || '';
  const img = src
    ? `<img src="${esc(src)}" alt="" loading="lazy"/>`
    : '<div class="sd-hero-placeholder">🐦</div>';
  const playable = (Array.isArray(d.recordings) && d.recordings.length) || !!d.audio_url;
  const badge = playable
    ? '<span class="sd-audio-badge" title="Vogelstimme verfügbar">🎵</span>'
    : '';
  return `<div class="sd-hero">${img}${badge}</div>`;
}

function _metaHtml(d) {
  const count = d.sighting_count || 0;
  // Small eyebrow label — the only remaining trace of the old standalone
  // "📖 Vogel-Dossiers" section heading, now living inside the panel
  // itself instead of a persistent header outside it (nothing to
  // duplicate: this panel IS the dossier, there's no second copy of the
  // label elsewhere on the page).
  return `<div class="sd-eyebrow">📖 Art-Dossier</div>
    <div class="sd-name">${esc(d.common_name_de || d.latin)}</div>
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

function _audioRowHtml(r) {
  const recordist = esc(r.recordist || 'unbekannt');
  const license = r.license_url
    ? ` · <a href="${esc(r.license_url)}" target="_blank" rel="noopener noreferrer">Lizenz</a>`
    : '';
  return `<div class="sd-audio-row">
    <span class="sd-audio-type">${esc(r.type_de || 'Aufnahme')}</span>
    <audio class="sd-audio-player" controls preload="none" src="${esc(r.file_url)}"></audio>
    <div class="sd-audio-attribution">♪ ${recordist}${license}</div>
  </div>`;
}

// Renders up to three labelled <audio controls> rows with mandatory
// attribution next to each player (CC-BY compliance — see
// bird_dossiers.py's module docstring). Falls back to the single-clip
// legacy fields for older dossiers that haven't been re-fetched.
function _audioHtml(d) {
  const list =
    Array.isArray(d.recordings) && d.recordings.length
      ? d.recordings.slice(0, 3)
      : d.audio_url
        ? [
            {
              file_url: d.audio_url,
              type_de: 'Aufnahme',
              recordist: d.audio_attribution,
              license_url: d.audio_license,
            },
          ]
        : [];
  if (!list.length) return '';
  return `<div class="sd-audio">
    ${list.map(_audioRowHtml).join('')}
    <div class="sd-audio-source">Quelle: <a href="https://xeno-canto.org/" target="_blank" rel="noopener noreferrer">xeno-canto.org</a></div>
  </div>`;
}

function _switcherHtml() {
  const opts = _dossiers
    .map((d) => {
      const sel = d.latin === _selectedLatin ? ' selected' : '';
      return `<option value="${esc(d.latin)}"${sel}>${esc(d.common_name_de || d.latin)}</option>`;
    })
    .join('');
  return `<div class="sd-switcher">
    <button type="button" class="sd-switch-btn" id="sdPrevBtn" aria-label="Vorherige Art">‹</button>
    <select class="sd-select" id="sdSelect" aria-label="Art wählen">${opts}</select>
    <button type="button" class="sd-switch-btn" id="sdNextBtn" aria-label="Nächste Art">›</button>
  </div>`;
}

function _leftColumnHtml(d) {
  const wikiLink = d.wikipedia_url
    ? `<a class="sd-wiki-link" href="${esc(d.wikipedia_url)}" target="_blank" rel="noopener noreferrer">Auf Wikipedia ansehen ↗</a>`
    : '';
  return `<div class="sd-card">
    ${_heroHtml(d)}
    ${_metaHtml(d)}
    ${_wikiHtml(d)}
    ${_audioHtml(d)}
    ${wikiLink}
    ${_switcherHtml()}
  </div>`;
}

function _wireLeftColumn() {
  byId('sdPrevBtn')?.addEventListener('click', () => _cycle(-1));
  byId('sdNextBtn')?.addEventListener('click', () => _cycle(1));
  byId('sdSelect')?.addEventListener('change', (e) => _selectSpecies(e.target.value, false));
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
  _wireLeftColumn();
  _loadClips(d);
}

function _selectSpecies(latin, scrollIntoView) {
  const d = _dossiers.find((x) => x.latin === latin);
  if (!d) return;
  _selectedLatin = latin;
  _renderPanel(d);
  if (scrollIntoView) {
    byId('speciesDossierPanel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}
