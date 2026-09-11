// ─── mediathek/bulk-delete.js ──────────────────────────────────────────────
// Stage 13 of the legacy.js → ES modules refactor — multi-select +
// bulk-delete machinery on the Mediathek drilldown grid. Toggle button
// flips body.media-select-mode; the bottom action bar shows the count
// + "Löschen" CTA. Backend takes a single POST with the event-id list
// and returns deleted/failed counts.
import { byId } from '../core/dom.js';
import { state } from '../core/state.js';
import { j } from '../core/api.js';
import { showToast, showConfirm } from '../core/toast.js';
import { refreshTimelineAndStats } from '../chrome/storage-stats.js';

// Exported so the mediathek/orchestration.js drilldown openers can
// re-use them without reaching through window. (Stage 23 extract.)
export function _updateMediaSelectToggle() {
  const btn = byId('mediaSelectToggleBtn');
  if (!btn) return;
  btn.style.display = state.mediaCamera ? 'inline-flex' : 'none';
  btn.classList.toggle('btn-action', state.mediaSelectMode);
  btn.classList.toggle('action-green', state.mediaSelectMode);
  btn.classList.toggle('btn-neutral', !state.mediaSelectMode);
  _repaintSelectAll();
}

/** „Ganze Seite markieren" lives in the pagination row now, beside the
 *  ‹ › that move between pages — „Seitenauswahl am besten direkt beim
 *  zur nächsten Seite springen". mediathek/_paging.js paints it from
 *  `state`, so every place that changes the selection just asks for a
 *  repaint instead of reaching into the button.
 *
 *  Through `window` rather than an import: _paging.js pulls in
 *  lightbox.js, which has top-level DOM side effects, and this module is
 *  loaded by the drilldown openers long before any grid exists. */
function _repaintSelectAll() {
  window.renderMediaPagination?.();
}

/** PURE: the event ids on the page currently rendered. `state.media` is
 *  the page slice (see mediathek/_paging.js), which is deliberately what
 *  "select all" means here — the whole library is not something an
 *  operator can look at before deleting it. */
export function pageEventIds(media) {
  return (media || []).map((m) => m && m.event_id).filter(Boolean);
}

/** PURE: does the page's selection already cover every id on it? */
export function pageFullySelected(ids, selected) {
  return ids.length > 0 && ids.every((id) => selected.has(id));
}

export function _exitMediaSelectMode() {
  state.mediaSelectMode = false;
  state.mediaSelected.clear();
  document.body.classList.remove('media-select-mode');
  const bar = byId('mediaSelectBar');
  if (bar) bar.style.display = 'none';
  document
    .querySelectorAll('.media-card.media-card--selected')
    .forEach((c) => c.classList.remove('media-card--selected'));
  _updateMediaSelectToggle();
}

export function _enterMediaSelectMode() {
  state.mediaSelectMode = true;
  state.mediaSelected.clear();
  document.body.classList.add('media-select-mode');
  _refreshMediaSelectBar();
  _updateMediaSelectToggle();
}

function _refreshMediaSelectBar() {
  const bar = byId('mediaSelectBar');
  if (!bar) return;
  if (!state.mediaSelectMode) {
    bar.style.display = 'none';
    return;
  }
  bar.style.display = '';
  const n = state.mediaSelected.size;
  const c = byId('msbCount');
  if (c) c.textContent = String(n);
  // A live-looking red „Löschen" beside a count of zero is a button that
  // promises an action it cannot perform. It greys out until there is
  // something to delete.
  const del = byId('msbDeleteBtn');
  if (del) del.disabled = n === 0;
}

// Inline onclick callsites in the grid card render rely on this — used
// from media cards' hidden checkbox toggle when select mode is on.
export function _toggleMediaSelected(eventId) {
  if (!eventId) return;
  if (state.mediaSelected.has(eventId)) state.mediaSelected.delete(eventId);
  else state.mediaSelected.add(eventId);
  const card = document.querySelector(`.media-card[data-event-id="${CSS.escape(eventId)}"]`);
  if (card) card.classList.toggle('media-card--selected', state.mediaSelected.has(eventId));
  _refreshMediaSelectBar();
  _repaintSelectAll();
}
window._toggleMediaSelected = _toggleMediaSelected;

/** Select every card on the current page — or, when they already all
 *  are, clear them. Only the PAGE: see pageEventIds. */
window.toggleSelectAllOnPage = function () {
  if (!state.mediaSelectMode) return;
  const ids = pageEventIds(state.media);
  const clearing = pageFullySelected(ids, state.mediaSelected);
  for (const id of ids) {
    if (clearing) state.mediaSelected.delete(id);
    else state.mediaSelected.add(id);
  }
  document.querySelectorAll('.media-card').forEach((card) => {
    const id = card.dataset?.eventId;
    if (id) card.classList.toggle('media-card--selected', state.mediaSelected.has(id));
  });
  _refreshMediaSelectBar();
  _repaintSelectAll();
};

window.toggleMediaSelectMode = function () {
  if (state.mediaSelectMode) _exitMediaSelectMode();
  else _enterMediaSelectMode();
};

/** PURE: the second question, in the operator's own words.
 *  `{Elster: 3, Amsel: 1}` → „Elster (3), Amsel (1)". */
export function speciesProofWarning(species) {
  const names = Object.entries(species || {}).map(([name, n]) => `${name} (${n})`);
  if (!names.length) return '';
  return (
    `Das sind die letzten Aufnahmen von ${names.join(', ')}. ` +
    `Ohne Beweisvideo verliert ${names.length > 1 ? 'diese Arten' : 'diese Art'} ` +
    `die Freischaltung im Sichtungs-Raster. Trotzdem löschen?`
  );
}

/** One bulk-delete POST. Returns the parsed result, or `null` when the
 *  server asked a question the operator answered with "no".
 *
 *  The server refuses with 409 + the affected species when a selection
 *  would take the LAST clip of one — see routes/events.py. That is not
 *  an error to surface as one; it is a second question, and answering it
 *  yes simply repeats the call with `force`. */
async function _postBulkDelete(camId, ids) {
  const url = `/api/camera/${encodeURIComponent(camId)}/events/delete-bulk`;
  const send = (force) =>
    j(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(force ? { event_ids: ids, force: true } : { event_ids: ids }),
    });
  try {
    return await send(false);
  } catch (e) {
    if (e?.status !== 409) throw e;
    let species = {};
    try {
      species = JSON.parse(e.message)?.species || {};
    } catch {
      species = {};
    }
    if (!(await showConfirm(speciesProofWarning(species)))) return null;
    return send(true);
  }
}

window.bulkDeleteSelectedMedia = async function () {
  const ids = Array.from(state.mediaSelected);
  const camId = state.mediaCamera;
  if (!camId || !ids.length) return;
  if (!(await showConfirm(`${ids.length} ausgewählte Einträge wirklich löschen?`))) return;
  try {
    const r = await _postBulkDelete(camId, ids);
    if (!r) return;
    const okSet = new Set(ids.filter((id) => !(r.failed || []).includes(id)));
    state._allMedia = (state._allMedia || []).filter((x) => !okSet.has(x.event_id));
    // calcItemsPerPage + renderMediaGrid + renderMediaPagination still
    // live in legacy.js; resolve via window until they extract too.
    const ps_d = typeof window.calcItemsPerPage === 'function' ? window.calcItemsPerPage() : 24;
    state.mediaTotalPages = Math.max(1, Math.ceil(state._allMedia.length / ps_d));
    state.mediaPage = Math.min(state.mediaPage || 0, state.mediaTotalPages - 1);
    state.media = state._allMedia.slice(state.mediaPage * ps_d, (state.mediaPage + 1) * ps_d);
    _exitMediaSelectMode();
    if (typeof window.renderMediaGrid === 'function') window.renderMediaGrid();
    if (typeof window.renderMediaPagination === 'function') window.renderMediaPagination();
    refreshTimelineAndStats();
    window.reloadLibraryPage?.();
    const failed = (r.failed || []).length;
    showToast(
      failed ? `${r.deleted} gelöscht, ${failed} fehlgeschlagen` : `${r.deleted} gelöscht`,
      failed ? 'error' : 'success',
    );
  } catch (e) {
    showToast('Bulk-Löschen fehlgeschlagen: ' + e.message, 'error');
  }
};
