// ─── library/_filter-state.js ────────────────────────────────────────────
// Stage 6 of the Mediathek + Wetter-Ereignisse merge: the merged grid's
// filter state + its mapping onto `/api/library`'s query params. Split
// out of _filter-bar.js (which also pulls in mediathek/filters.js for
// its label vocabulary, and through that the whole Mediathek module
// graph) so this pure half stays importable on its own — same "plain
// state machine, DOM-free" split library/_pagination.js already uses
// for its own reason, see that file's own header.
//
// The Wetterdaten chart's drag-zoom USED to be a second source of query
// params here. It is gone: a filter whose control lives in a different
// section of the page, far below the grid it narrows, reads as a bug
// rather than a filter. See libraryQueryParams for the whole reasoning.

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
  // NO `since`/`until` FROM THE WEATHER CHART. Dragging a span in the
  // Wetterdaten graph used to narrow this grid to the same window, and
  // the two live far apart on the page: the operator zoomed the graph,
  // scrolled up, and found „Keine Einträge im gewählten Zeitraum" with
  // nothing on screen explaining why — „der Zeitraum von dem
  // Wettergrafen darf nicht die Mediathek bestimmen, also lös da die
  // Verbindung".
  //
  // The chart keeps its own zoom; this grid keeps its own filter. A
  // control has to sit next to what it controls.
  return params;
}
