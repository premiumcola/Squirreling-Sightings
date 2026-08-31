// ─── library/_filter-state.js ────────────────────────────────────────────
// Stage 6 of the Mediathek + Wetter-Ereignisse merge: the merged grid's
// filter state + its mapping onto `/api/library`'s query params. Split
// out of _filter-bar.js (which also pulls in mediathek/filters.js for
// its label vocabulary, and through that the whole Mediathek module
// graph) so this pure half stays importable on its own — same "plain
// state machine, DOM-free" split library/_pagination.js already uses
// for its own reason, see that file's own header.
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
  return params;
}
