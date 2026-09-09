// ─── weather/_zoom.js ───────────────────────────────────────────────────
// Shared drag-to-zoom range state for the Wetterdaten-chart. Lives in
// its own leaf module — outside stats.js (which drives the chart) and
// weather/_manual-event-save.js (the "als Ereignis speichern" flow) —
// so both can read/write it without importing one another.
//
// It narrows the CHART and nothing else. The merged Mediathek grid once
// narrowed by the same range (Stage 7) and no longer does anywhere:
// query params (library/_filter-state.js), the empty-state wording
// (library/_grid.js) and the "gefiltert" banner (library/page.js) have
// all been unhooked. weather/_time-binding.js goes one step further and
// CLEARS this range as soon as a filter up in the Mediathek is used, so
// a span dragged down here cannot outlive the operator's attention. It
// imports from this file, never the other way round — the cross-import
// cycle this module's leaf-ness exists to avoid.
//
// Boundaries are the RAW `ts` string of whichever sample the drag
// snapped to (see stats-chart/_hover.js's brush handler), never a
// re-derived Date().toISOString() — every timestamp elsewhere in this
// app (sample.ts, sighting.started_at, …) is a naive "local wall-clock"
// ISO string with no zone offset, and round-tripping through
// toISOString() would silently reinterpret it as UTC. Lexical string
// comparison is exact for that fixed-width, zero-padded family, so no
// Date() parsing happens here at all.

let _range = null; // { start: isoString, end: isoString } | null

export function setZoomRange(startIso, endIso) {
  _range = startIso <= endIso ? { start: startIso, end: endIso } : { start: endIso, end: startIso };
}

export function clearZoomRange() {
  _range = null;
}

export function getZoomRange() {
  return _range;
}

export function isZoomActive() {
  return _range !== null;
}

// Slice a fetched history payload's samples down to the active zoom
// range. Returns `samples` unchanged when no zoom is active.
export function zoomedSamples(samples) {
  if (!_range || !Array.isArray(samples)) return samples;
  return samples.filter((s) => s.ts >= _range.start && s.ts <= _range.end);
}

// Whether an ISO timestamp falls inside the active zoom range; always
// true when no zoom is active. Not called by anything — the merged grid
// that Stage 7 briefly narrowed by this range never used it either
// (server-side `since`/`until` did that job, and that whole coupling is
// gone now). Kept as this module's public contract for whichever future
// consumer DOES need a client-side per-item membership test, same as
// sightings.js's old grid filter used to.
export function withinZoom(tsIso) {
  if (!_range) return true;
  if (!tsIso) return false;
  return tsIso >= _range.start && tsIso <= _range.end;
}
