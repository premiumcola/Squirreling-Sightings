// ─── library/_bind.js ────────────────────────────────────────────────────
// Stage 6 of the Mediathek + Wetter-Ereignisse merge: wires the
// interactive bits `library/_grid.js` renders as inert HTML — click-
// to-open, delete, pin — onto whichever existing opener/handler already
// owns that kind. No new interaction model: every handler below re-
// attaches the SAME opener the old per-kind grid used.
//
// Motion cards mostly need no wiring here — `mediathek/_cards.js::
// mediaCardHTML` embeds its click/confirm/delete handlers as inline
// onclicks (`window._openMediaItem` / `window.deleteMediaCard` /
// `window.confirmMediaCard`), so they fire on their own. `deleteMediaCard`
// / `confirmMediaCard` are installed unconditionally at module load
// (mediathek/orchestration.js top level) — always there.
//
// `window._openMediaItem` is NOT: its only definition lives inside
// mediathek/_paging.js::renderMediaGrid, reassigned every time the
// per-camera DRILLDOWN paints. Before the library merge that was fine —
// the drilldown was the only place a motion card could ever be clicked
// from. Now a motion card can render in THIS grid before the operator
// has ever opened a single camera's drilldown, and the inline onclick
// throws into a `window._openMediaItem` that plain doesn't exist yet —
// silently, since a broken inline onclick has nowhere to report to.
// "Today's bird clip does nothing when tapped" was exactly this: no
// drilldown had been opened yet.
//
// Fix: install it here too, freshest-render-wins exactly like the
// drilldown does — resolve from THIS page's items first (adaptMotionItem
// already carries the full event payload in `extra`), fall back to the
// shared registry (mediathek/_item-registry.js) for a card painted by
// the OTHER grid. Ignores state.mediaSelectMode on purpose: bulk-select
// is a drilldown-only affordance (#mediaSelectBar lives there, not in
// this grid) — a merged-grid card always just opens.
import { state } from '../core/state.js';
import { showToast } from '../core/toast.js';
import { openLightbox } from '../lightbox.js';
import { bindPinToggle } from '../weather/pin-toggle.js';
import { openWeatherLightbox, openWeatherRecapLightbox } from '../weather/_lightbox.js';
import { openStormEpisode } from '../weather/_feed.js';
import { deleteSighting } from '../weather/sightings.js';
import { openManualEventView } from '../weather/_manual-events.js';
import { getRegisteredMediaItem, registerMediaItems } from '../mediathek/_item-registry.js';
import { adaptMotionItem } from './_motion-adapter.js';
import { resolveMotionItem } from './_motion-open.js';

function _registerMotionItems(page) {
  const items = page.filter((it) => it.kind === 'motion').map(adaptMotionItem);
  registerMediaItems(items);
  window._openMediaItem = (id) => {
    const item = resolveMotionItem(items, id, getRegisteredMediaItem);
    if (item) openLightbox(item);
  };
}

function _bindSightingCards(grid) {
  grid.querySelectorAll('.ws-card').forEach((card) => {
    card.addEventListener('click', () => {
      const id = card.dataset.id;
      const idx = (state.weather.items || []).findIndex((s) => s.id === id);
      if (idx >= 0) openWeatherLightbox(idx);
    });
  });
  grid.querySelectorAll('.ws-card .mmc-delete').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const card = btn.closest('.ws-card');
      if (card) deleteSighting(card.dataset.id, card);
    });
  });
  grid.querySelectorAll('.ws-score-chip').forEach((b) => {
    const tip = b.getAttribute('data-score-tip');
    if (!tip) return;
    const fire = (e) => {
      e.stopPropagation();
      showToast(tip, 'info');
    };
    b.addEventListener('click', fire);
    b.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        fire(e);
      }
    });
  });
}

function _bindRecapCards(grid) {
  grid.querySelectorAll('.ws-recap-card[data-recap-idx]').forEach((card) => {
    card.addEventListener('click', () => {
      const id = card.dataset.id;
      const full = (state.weather.recaps || []).find((r) => r.id === id);
      openWeatherRecapLightbox(full || { id });
    });
  });
}

function _bindEpisodeCards(grid) {
  grid.querySelectorAll('.ws-recap-card[data-ep-id]').forEach((card) => {
    card.addEventListener('click', () => openStormEpisode(card.dataset.epId));
  });
}

function _bindManualCards(grid) {
  grid.querySelectorAll('.ws-recap-card[data-manual-id]').forEach((card) => {
    card.addEventListener('click', () => openManualEventView(card.dataset.manualId));
  });
}

// Timelapse cards carry no click affordance of their own
// (`library/_timelapse-card.js` is a read-only preview — see that
// file's header) — the raw clip is still reachable, one tap away, via
// the item's own `video_url`. Full QA/delete/rebuild tooling stays on
// the Mediathek drilldown's own `.mmc-tl` cards, unaffected by this.
function _bindTimelapseCards(grid, itemsById) {
  grid.querySelectorAll('.mmc-tl[data-lib-id]').forEach((card) => {
    card.addEventListener('click', () => {
      const item = itemsById.get(card.dataset.libId);
      if (item?.video_url) window.open(item.video_url, '_blank');
    });
  });
}

/** Wire every interactive affordance in a freshly-painted library page. */
export function bindLibraryGrid(grid, page) {
  if (!grid) return;
  const itemsById = new Map(page.map((it) => [it.id, it]));
  _registerMotionItems(page);
  _bindSightingCards(grid);
  _bindRecapCards(grid);
  _bindEpisodeCards(grid);
  _bindManualCards(grid);
  _bindTimelapseCards(grid, itemsById);
  bindPinToggle(grid);
}
