// ─── core/polygon-source.js ────────────────────────────────────────────────
// Single source of truth for "what coordinate space was this polygon
// authored in." Every consumer of zones/masks (recorded lightbox,
// live-sim, cam-edit re-render) routes through these helpers so they
// can never disagree about the polygon's reference frame.
//
// Authoring chain — cam-edit/shape-editor draws polygons over the
// camera's snapshot (substream-priority, via /api/camera/<id>/snapshot.jpg).
// The editor's canvas is sized to the image's naturalWidth × naturalHeight
// and the polygon's `source_w` / `source_h` get stamped from those at
// save time (see shape-editor/pointer.js · _commitInProgressPolygon).
// For polygons saved BEFORE the stamping logic landed, we recover the
// authored resolution from the camera's reported substream size
// (`cam.preview_resolution`) — that string is exactly what the editor
// would have produced if it were re-opened today.
//
// Critically: the AUTHORED resolution is NEVER derived from the
// rendered <video>/<img>'s natural dimensions or the displayed
// element's CSS box. The main-stream is at a different resolution
// (and sometimes a different aspect ratio) than the substream the
// polygon was drawn against — using main-stream as the source space
// stretches/squashes the polygon to the wrong shape.

/** Parse a "WxH" / "W×H" string into {w, h}. Returns null when the
 *  string is missing or malformed. */
function _parseRes(str) {
  if (!str) return null;
  const m = String(str).match(/(\d+)\s*[x×]\s*(\d+)/);
  if (!m) return null;
  const w = parseInt(m[1], 10);
  const h = parseInt(m[2], 10);
  if (!w || !h) return null;
  return { w, h };
}

/**
 * Resolve a sensible fallback authoring resolution for a camera.
 * Returns the substream dims when the camera has them, then any
 * configured detection_resolution, then a 1280×720 last-ditch
 * default (the shape-editor's hard-coded fallback when no snapshot
 * loads — same constant in `shape-editor/canvas.js#scaleForCanvas`).
 */
export function resolveCamSourceDims(cam) {
  const fromPreview = _parseRes(cam && cam.preview_resolution);
  if (fromPreview) return fromPreview;
  const fromDetect = _parseRes(cam && cam.detection_resolution);
  if (fromDetect) return fromDetect;
  return { w: 1280, h: 720 };
}

/**
 * Resolve the AUTHORED source dims for a single polygon. Polygons
 * carrying their own `source_w` / `source_h` always win — those were
 * stamped at save time and are gospel. Anything missing falls back
 * to the camera's authoring resolution.
 */
export function resolvePolygonSourceDims(polygon, cam) {
  if (polygon && typeof polygon === 'object' && polygon.source_w > 0 && polygon.source_h > 0) {
    return { w: polygon.source_w, h: polygon.source_h };
  }
  return resolveCamSourceDims(cam);
}

/**
 * Normalise a polygon into the {points, source_w, source_h, ...}
 * shape every read-only renderer expects. Handles both the legacy
 * bare-array form ([{x,y},...]) and the modern object form
 * ({points, source_w, source_h}). Always returns an object with
 * explicit source_w / source_h so downstream renderers never need
 * to second-guess the reference frame.
 */
export function normalizePolygon(polygon, cam) {
  if (!polygon) return null;
  const dims = resolvePolygonSourceDims(polygon, cam);
  if (Array.isArray(polygon)) {
    return { points: polygon, source_w: dims.w, source_h: dims.h };
  }
  const out = { ...polygon };
  out.source_w = dims.w;
  out.source_h = dims.h;
  return out;
}
