// ─── sichtungen/_drilldown.js ────────────────────────────────────────────
// Inline accordion showing an unlocked MAMMAL species' own camera clips
// below the achievement grid (/api/achievements/<id>/media). Split out
// of the former sichtungen.js monolith unchanged.
//
// Bird species no longer use this path — a bird tile (locked or
// unlocked) opens the redesigned species dossier panel instead (see
// _dossier-panel.js), which already shows the same "own clips" grid
// alongside the Wikipedia/Xeno-canto reference content. Mammals have no
// dossier data (bird_dossiers.py is bird-only), so they keep this
// simpler, clips-only accordion.
import { byId } from '../core/dom.js';
import { state } from '../core/state.js';
import { j } from '../core/api.js';
import { mediaCardHTML } from '../mediathek/orchestration.js';

// State is module-level so the renderer can reflect the open card with
// an outline+highlight and the wrap stays consistent across re-renders.
let _achOpenId = null;
let _achDrillItems = [];
let _achDrillTotal = 0;
let _achDrillPage = 0;
const _ACH_DRILL_LIMIT = 24;
let _achDrillLoading = false;

// Lightbox navigation uses state.media — we save whatever was there so
// the main Mediathek keeps its own list intact while the user pages
// through a Sichtungen drilldown.
let _achDrillSavedMedia = null;

export function _currentAchOpenId() {
  return _achOpenId;
}

function _achDrillStashMedia() {
  if (_achDrillSavedMedia === null) _achDrillSavedMedia = state.media;
  state.media = _achDrillItems;
}
function _achDrillRestoreMedia() {
  if (_achDrillSavedMedia !== null) {
    state.media = _achDrillSavedMedia;
    _achDrillSavedMedia = null;
  }
}

async function _achDrillFetch(speciesId, offset) {
  try {
    const r = await j(
      `/api/achievements/${encodeURIComponent(speciesId)}/media?limit=${_ACH_DRILL_LIMIT}&offset=${offset}`,
    );
    return r || { items: [], total_count: 0 };
  } catch {
    return { items: [], total_count: 0 };
  }
}

function _achDrillRenderItems() {
  const grid = byId('achDrillGrid');
  if (!grid) return;
  if (!_achDrillItems.length) {
    grid.innerHTML =
      '<div class="item muted" style="padding:16px;grid-column:1/-1">Noch keine archivierten Aufnahmen für diese Art.</div>';
  } else {
    grid.innerHTML = _achDrillItems.map(mediaCardHTML).join('');
  }
  const more = byId('achDrillMore');
  if (more) {
    more.style.display = _achDrillItems.length < _achDrillTotal ? '' : 'none';
  }
  const countEl = byId('achDrillCount');
  if (countEl) {
    const shown = _achDrillItems.length;
    countEl.textContent = _achDrillTotal <= shown ? `${shown}` : `${shown} von ${_achDrillTotal}`;
  }
  // Cards click → openLightbox with our item list in scope.
  _achDrillStashMedia();
  grid.querySelectorAll('.media-card').forEach((card) => {
    const eid = card.dataset.eventId;
    card.style.cursor = 'pointer';
    card.onclick = (ev) => {
      // Leave stop-propagation for inner buttons (confirm/delete already
      // call event.stopPropagation() in their onclick), so this only
      // fires when the card body itself is clicked.
      if (ev.target.closest('.mmc-actions, .media-confirmed-badge')) return;
      const it = _achDrillItems.find((x) => x.event_id === eid);
      if (it && typeof window.openLightbox === 'function') window.openLightbox(it);
    };
  });
}

export async function toggleAchDrilldown(id, name, renderAchievements) {
  // Second click on the same card → close.
  if (_achOpenId === id) {
    closeAchDrilldown(renderAchievements);
    return;
  }
  _achOpenId = id;
  _achDrillItems = [];
  _achDrillTotal = 0;
  _achDrillPage = 0;
  // Re-render grid so the previous active card loses its highlight and
  // the newly-active one gains it; the drilldown wrap below the grid
  // is recreated empty as part of that render.
  renderAchievements();
  const wrap = byId('achDrilldownWrap');
  if (!wrap) return;
  const nameEl = byId('achDrillName');
  if (nameEl) nameEl.textContent = name || id;
  const grid = byId('achDrillGrid');
  if (grid)
    grid.innerHTML =
      '<div class="field-help" style="padding:16px;grid-column:1/-1">Lade Sichtungen…</div>';
  // Expand the accordion first so the fetch result slots into a
  // visible container.
  wrap.classList.add('ach-drilldown-wrap--open');
  // Scroll the drilldown into view once the height transition starts.
  setTimeout(() => {
    byId('achDrilldownWrap')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, 60);
  _achDrillLoading = true;
  const r = await _achDrillFetch(id, 0);
  _achDrillLoading = false;
  // Check the user didn't close / switch the drilldown while waiting.
  if (_achOpenId !== id) return;
  _achDrillItems = r.items || [];
  _achDrillTotal = r.total_count || 0;
  _achDrillRenderItems();
}

export async function loadMoreAchDrill() {
  if (!_achOpenId || _achDrillLoading) return;
  _achDrillLoading = true;
  _achDrillPage += 1;
  const r = await _achDrillFetch(_achOpenId, _achDrillPage * _ACH_DRILL_LIMIT);
  _achDrillLoading = false;
  if (r && r.items && r.items.length) {
    _achDrillItems = _achDrillItems.concat(r.items);
    _achDrillTotal = r.total_count || _achDrillItems.length;
    _achDrillRenderItems();
  }
}

export function closeAchDrilldown(renderAchievements) {
  const wrap = byId('achDrilldownWrap');
  if (wrap) wrap.classList.remove('ach-drilldown-wrap--open');
  _achOpenId = null;
  _achDrillItems = [];
  _achDrillTotal = 0;
  _achDrillPage = 0;
  _achDrillRestoreMedia();
  if (renderAchievements) renderAchievements();
}

// Re-populate the grid from the in-memory cache when the achievement
// grid re-renders while a drilldown is open — the user sees items
// immediately instead of a "Lade…" placeholder on every unrelated
// re-render (e.g. re-selecting a species dossier elsewhere on the page).
export function _reflowAchDrilldownIfOpen() {
  if (_achOpenId && _achDrillItems.length) {
    _achDrillRenderItems();
  }
}
