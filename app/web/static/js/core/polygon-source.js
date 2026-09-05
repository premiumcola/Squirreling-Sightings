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

/** How many points a curved segment is sampled into.
 *  MUST match `flatten_poly_points`' default in app/app/mask_zones.py —
 *  a mask the pipeline applies and a mask the player draws have to be
 *  the same shape, not merely a similar one. */
export const POLY_CURVE_SAMPLES = 12;

/**
 * PURE: a polygon as a flat point list, sampling any curved segments.
 *
 * THE JS TWIN of `mask_zones.flatten_poly_points`, and it exists because
 * the two halves had drifted apart in the one way that matters. A zone
 * or mask may carry a `curves` array — a quadratic-Bézier control point
 * per segment — and the PIPELINE samples it before testing a detection
 * against the shape. Every reader on this side ignored `curves` and used
 * `points` alone, so a curved mask was DRAWN as straight lines, and the
 * player's own „is this box masked" test asked about a different polygon
 * than the one that actually filtered the detection. The overlay exists
 * to explain why something was excluded; a mask drawn in the wrong shape
 * explains the wrong thing.
 *
 * Same three input shapes as the Python side: a bare array is already
 * flat, a dict without usable curves keeps its points, and a dict with
 * curves gets `POLY_CURVE_SAMPLES` intermediate points per segment. The
 * closing segment back to points[0] is implicit — every consumer closes
 * the path itself.
 */
export function flattenPolyPoints(poly, samples = POLY_CURVE_SAMPLES) {
  if (Array.isArray(poly)) return poly;
  if (!poly || typeof poly !== 'object') return [];
  const pts = Array.isArray(poly.points) ? poly.points : [];
  if (pts.length < 2) return pts;
  const curves = poly.curves;
  if (!Array.isArray(curves) || curves.every((c) => c == null)) return pts;
  const out = [];
  const n = pts.length;
  for (let i = 0; i < n; i++) {
    const p0 = pts[i];
    const p1 = pts[(i + 1) % n];
    out.push({ x: Math.round(p0?.x || 0), y: Math.round(p0?.y || 0) });
    const cp = curves[i];
    if (!cp || typeof cp.x !== 'number' || typeof cp.y !== 'number') continue;
    for (let k = 1; k <= samples; k++) {
      const t = k / (samples + 1);
      const u = 1 - t;
      out.push({
        x: Math.round(u * u * (p0?.x || 0) + 2 * u * t * cp.x + t * t * (p1?.x || 0)),
        y: Math.round(u * u * (p0?.y || 0) + 2 * u * t * cp.y + t * t * (p1?.y || 0)),
      });
    }
  }
  return out;
}

/**
 * Normalise a polygon into the {points, source_w, source_h, ...}
 * shape every read-only renderer expects. Handles both the legacy
 * bare-array form ([{x,y},...]) and the modern object form
 * ({points, source_w, source_h}). Always returns an object with
 * explicit source_w / source_h so downstream renderers never need
 * to second-guess the reference frame.
 *
 * The points come out FLATTENED, once, here — so a curved shape is a
 * curve for everything downstream (the canvas that draws it and the
 * point-in-polygon test that decides whether a box is masked) without
 * either of them having to know that `curves` exists.
 */
export function normalizePolygon(polygon, cam) {
  if (!polygon) return null;
  const dims = resolvePolygonSourceDims(polygon, cam);
  if (Array.isArray(polygon)) {
    return { points: polygon, source_w: dims.w, source_h: dims.h };
  }
  const out = { ...polygon };
  out.points = flattenPolyPoints(polygon);
  out.source_w = dims.w;
  out.source_h = dims.h;
  return out;
}
