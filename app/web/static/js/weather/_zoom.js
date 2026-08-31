// ─── weather/_zoom.js ───────────────────────────────────────────────────
// Shared drag-to-zoom range state for the Wetterdaten-chart. Lives in
// its own leaf module — outside both stats.js (which drives the chart)
// and sightings.js (which filters the unified grid by the same range) —
// so the two can each read/write it without importing one another.
// stats.js also needs to trigger a grid re-render when the range
// changes, which if this state lived inside either of those two modules
// would force exactly the cross-import cycle this file exists to avoid.
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
// true when no zoom is active. Not called by anything today — the
// merged library grid (Stage 6) does not narrow by this range, on
// purpose (see library/page.js's own header for why that wiring is a
// later stage) — kept as this module's public contract for that stage
// to reach for, same as sightings.js's old grid filter used to.
export function withinZoom(tsIso) {
  if (!_range) return true;
  if (!tsIso) return false;
  return tsIso >= _range.start && tsIso <= _range.end;
}
