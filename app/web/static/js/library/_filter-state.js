// ─── library/_filter-state.js ────────────────────────────────────────────
// Stage 6 of the Mediathek + Wetter-Ereignisse merge: the merged grid's
// filter state + its mapping onto `/api/library`'s query params. Split
// out of _filter-bar.js (which also pulls in mediathek/filters.js for
// its label vocabulary, and through that the whole Mediathek module
// graph) so this pure half stays importable on its own — same "plain
// state machine, DOM-free" split library/_pagination.js already uses
// for its own reason, see that file's own header.
//
// Stage 7 adds the Wetterdaten-chart's drag-zoom as a SECOND source of
// query params, composed here rather than as a parallel fetch-time
// mechanism: `getZoomRange`/`isZoomActive` (weather/_zoom.js, a leaf
// module — no cycle risk importing it from here) are read at the same
// point camera/label/category chips already are, so `since`/`until`
// end up in the exact same URLSearchParams as everything else instead
// of a third, independent filter-state channel. The chart's own
// lifecycle (weather/stats.js's onWeatherChartRangeSelect /
// resetWeatherChartZoom) still triggers the actual refetch via the
// established `window.reloadLibraryPage` bridge — this file only
// answers "what does the CURRENT state map onto", the same question it
// already answered for the three chip groups.
import { getZoomRange } from '../weather/_zoom.js';

export function createLibraryFilterState() {
  return { cameraIds: new Set(), labels: new Set(), categories: new Set() };
}

/** `filter` state → the `/api/library` query params it maps onto. No
 * `kinds` ever set here — "Alles gemischt" (every kind, server default)
 * is this feed's own default and this grid's only view. */
export function libraryQueryParams(filter) {
  const params = new URLSearchParams();
  if (filter.cameraIds.size) params.set('camera_ids', [...filter.cameraIds].join(','));
  if (filter.labels.size) params.set('labels', [...filter.labels].join(','));
  if (filter.categories.size) params.set('categories', [...filter.categories].join(','));
  const zoom = getZoomRange();
  if (zoom) {
    params.set('since', zoom.start);
    params.set('until', zoom.end);
  }
  return params;
}
