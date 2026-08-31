// ─── mediathek/_actions.js ─────────────────────────────────────────────────
// R23 split of orchestration.js — the three per-tile actions the inline
// onclicks in _cards.js reach for: delete a motion event, delete a
// timelapse, confirm an event. Each one talks to /api/camera/<id>/… and
// then re-slices the loaded library so the grid and the pagination bar
// agree with what is left.
//
// They are bridged onto window from orchestration.js because the buttons
// carry inline onclick attributes; when those migrate to delegated
// listeners these become plain imports.
import { byId } from '../core/dom.js';
import { state } from '../core/state.js';
import { j } from '../core/api.js';
import { showToast } from '../core/toast.js';
import { refreshTimelineAndStats } from '../chrome/storage-stats.js';
import { renderMediaGrid, renderMediaPagination, _dropEventAndReslice } from './_paging.js';

export async function deleteMediaCard(btn) {
  const card = btn.closest('.media-card');
  const eventId = card?.dataset.eventId;
  const camId = card?.dataset.cameraId;
  if (!eventId || !camId) return;
  try {
    await j(`/api/camera/${encodeURIComponent(camId)}/events/${encodeURIComponent(eventId)}`, {
      method: 'DELETE',
    });
    // Brief fade-out animation, then re-render
    if (card) {
      card.style.transition = 'opacity .25s,transform .25s';
      card.style.opacity = '0';
      card.style.transform = 'scale(0.95)';
    }
    setTimeout(() => {
      _dropEventAndReslice(eventId);
      renderMediaGrid();
      renderMediaPagination();
      refreshTimelineAndStats();
      window.reloadLibraryPage?.();
    }, 250);
  } catch (e) {
    showToast('Löschen fehlgeschlagen: ' + e.message, 'error');
  }
}

export async function deleteTLCard(camId, filename, eventId) {
  try {
    await j(`/api/camera/${encodeURIComponent(camId)}/timelapse/${encodeURIComponent(filename)}`, {
      method: 'DELETE',
    });
    // Remove the unified EventStore entry too (server also does this as a backstop)
    if (eventId) {
      try {
        await j(`/api/camera/${encodeURIComponent(camId)}/events/${encodeURIComponent(eventId)}`, {
          method: 'DELETE',
        });
      } catch (_) {
        /* already cleaned by server */
      }
    }
    const card = byId('mediaGrid').querySelector(`[data-event-id="${CSS.escape(eventId)}"]`);
    if (card) card.remove();
    _dropEventAndReslice(eventId);
    renderMediaGrid();
    renderMediaPagination();
    if (!byId('mediaGrid').querySelector('.media-card')) {
      byId('mediaGrid').innerHTML =
        '<div class="item muted" style="padding:16px">Keine Medien vorhanden.</div>';
    }
    refreshTimelineAndStats();
    window.reloadLibraryPage?.();
  } catch (e) {
    showToast('Löschen fehlgeschlagen: ' + e.message, 'error');
  }
}

export async function confirmMediaCard(camId, eventId, btn) {
  // Brief scale animation on tap
  if (btn) {
    btn.classList.add('mmc-confirm--anim');
    setTimeout(() => btn.classList.remove('mmc-confirm--anim'), 200);
  }
  try {
    await j(
      `/api/camera/${encodeURIComponent(camId)}/events/${encodeURIComponent(eventId)}/confirm`,
      { method: 'POST' },
    );
    // update state.media + state._allMedia in place so lightbox nav and re-renders stay in sync
    const sIdx = (state.media || []).findIndex((x) => x.event_id === eventId);
    if (sIdx >= 0) state.media[sIdx].confirmed = true;
    const aIdx = (state._allMedia || []).findIndex((x) => x.event_id === eventId);
    if (aIdx >= 0) state._allMedia[aIdx].confirmed = true;
    const card = byId('mediaGrid').querySelector(`[data-event-id="${CSS.escape(eventId)}"]`);
    if (card) {
      // Wait for the scale anim to finish, then swap actions for the ✓ badge
      setTimeout(() => {
        card.classList.add('mmc-confirmed');
        const actions = card.querySelector('.mmc-actions');
        if (actions) actions.outerHTML = '<span class="media-confirmed-badge">✓</span>';
      }, 200);
    }
  } catch (e) {
    showToast('Bestätigen fehlgeschlagen: ' + e.message, 'error');
  }
}
