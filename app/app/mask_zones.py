"""Exclusion-mask / inclusion-zone geometry, shared by every detection path.

The polygon flattening, the compiled rasters and the per-detection
point-in-polygon tests used to exist only as ``ZonesMixin`` methods, i.e. as
INSTANCE STATE on the live ``CameraRuntime``. The Simulieren panel then
called those bound methods on the running runtime, which turned a read-only
diagnostic into a writer of live pipeline state.

That is not a theoretical hazard. ``_ensure_mask_image`` published the
config signature BEFORE the raster it describes::

    self._mask_sig = sig      # "cache is current"
    ...                       # <- alarm loop reads self._mask_image here
    self._mask_image = mask   # only now is that true

A sim tick that entered that window while the alarm loop was between its
own ``_ensure_mask_image()`` and its ``mask_resized[cy, cx]`` lookup left
the loop reading ``None`` behind a signature that said "current": the
operator's exclusion mask off, silently, in production, on a camera whose
whole job is to not miss an intruder.

So the geometry is pure and lives here, and each path owns its OWN
:class:`MaskZoneCache` — the runtime one for the alarm loop and the motion
gate, a sim-local one for the panel. Configuration is shared, state is not.
Both caches build the raster first and publish the signature last, so even
a future second reader of one cache can never see the inverted pair above.
"""

from __future__ import annotations

import json as _json_mod
import logging

import cv2
import numpy as np

log = logging.getLogger(__name__)

# Canonical raster size every compiled mask / zone image is drawn at.
# Frames are resized onto it at filter time, so any camera resolution works.
CANVAS_W = 1280
CANVAS_H = 720


def flatten_poly_points(poly, samples_per_curve: int = 12) -> list:
    """Return the polygon as a flat list of {x,y} points, sampling any
    curved segments via quadratic-bezier interpolation.

    `samples_per_curve` is the number of intermediate points between a
    segment's two endpoints; the endpoints themselves are always
    included once each. Three accepted input shapes mirror the JS-side
    _polyPoints + _polyCurves:
      - Bare list of points: returned as-is (legacy pre-label format).
      - Dict with no "curves" key (or all-null curves): "points" is
        returned unchanged.
      - Dict with curves: each segment i appends points[i] then, if
        curves[i] is a {x,y} control point, `samples_per_curve` bezier
        samples between points[i] and points[(i+1) % N]. Bezier formula
        per axis: B(t) = (1-t)^2 * p0 + 2(1-t)t * cp + t^2 * p1.
        Polygon close-back to points[0] is implicit — callers feed the
        result to cv2.fillPoly / cv2.pointPolygonTest which close
        automatically.
    """
    if isinstance(poly, list):
        return poly
    if not isinstance(poly, dict):
        return []
    pts = poly.get("points") or []
    if not isinstance(pts, list) or len(pts) < 2:
        return pts if isinstance(pts, list) else []
    curves = poly.get("curves")
    if not isinstance(curves, list) or all(c is None for c in curves):
        return pts
    out: list = []
    n = len(pts)
    for i in range(n):
        p0 = pts[i]
        p1 = pts[(i + 1) % n]
        out.append({"x": int(p0.get("x", 0)), "y": int(p0.get("y", 0))})
        cp = curves[i] if i < len(curves) else None
        if isinstance(cp, dict) and "x" in cp and "y" in cp:
            p0x = float(p0.get("x", 0))
            p0y = float(p0.get("y", 0))
            p1x = float(p1.get("x", 0))
            p1y = float(p1.get("y", 0))
            cpx = float(cp["x"])
            cpy = float(cp["y"])
            for k in range(1, samples_per_curve + 1):
                t = k / (samples_per_curve + 1)
                u = 1.0 - t
                bx = u * u * p0x + 2.0 * u * t * cpx + t * t * p1x
                by = u * u * p0y + 2.0 * u * t * cpy + t * t * p1y
                out.append({"x": int(bx), "y": int(by)})
    return out


def point_in_poly(
    cx: int,
    cy: int,
    points: list,
    frame_w: int,
    frame_h: int,
    source_w: int = CANVAS_W,
    source_h: int = CANVAS_H,
) -> bool:
    """pn834 — polygon points sit in their own source coord space
    (recorded on save as source_w / source_h). Rescale the frame
    centre into that space before the point-in-polygon test so a
    polygon drawn against a 640×360 substream snapshot still
    suppresses detections in a 2560×1440 main-stream frame
    correctly. Legacy polygons without source_w/h fall back to
    the historical 1280×720 default the caller passes here."""
    sx = float(source_w) / max(1, frame_w)
    sy = float(source_h) / max(1, frame_h)
    try:
        arr = np.array([[int(p.get('x', 0)), int(p.get('y', 0))] for p in points], dtype=np.int32)
    except Exception:
        return False
    if len(arr) < 3:
        return False
    return cv2.pointPolygonTest(arr, (float(cx) * sx, float(cy) * sy), False) >= 0


def signature(polys) -> str:
    """Stable serialisation used to decide whether a raster needs rebuilding."""
    try:
        return _json_mod.dumps(polys, sort_keys=True, separators=(',', ':'))
    except Exception:
        return repr(polys)


def authored_vertex_count(polys) -> int:
    """Vertices the OPERATOR clicked, not the sampled bezier polyline.

    "12 vertices" is what the user drew; "60 vertices" is what
    :func:`flatten_poly_points` made of it, and only the first is a number
    the operator can check against the editor.
    """
    total = 0
    for p in polys or ():
        pts = p.get("points", p) if isinstance(p, dict) else p
        if isinstance(pts, list):
            total += len(pts)
    return total


def _fill(canvas, polys, colour: int) -> None:
    """Draw every usable polygon onto the canvas at ``colour``.

    Polygons saved before the editor recorded a source space fall back to
    the canvas size, i.e. no rescale.
    """
    for poly in polys:
        pts_list = flatten_poly_points(poly)
        if not isinstance(pts_list, list) or len(pts_list) < 3:
            continue
        src_w = int(poly.get("source_w") or CANVAS_W) if isinstance(poly, dict) else CANVAS_W
        src_h = int(poly.get("source_h") or CANVAS_H) if isinstance(poly, dict) else CANVAS_H
        sx = float(CANVAS_W) / max(1, src_w)
        sy = float(CANVAS_H) / max(1, src_h)
        pts = np.array(
            [[int(p.get('x', 0) * sx), int(p.get('y', 0) * sy)] for p in pts_list],
            dtype=np.int32,
        )
        pts[:, 0] = np.clip(pts[:, 0], 0, CANVAS_W - 1)
        pts[:, 1] = np.clip(pts[:, 1], 0, CANVAS_H - 1)
        cv2.fillPoly(canvas, [pts], colour)


def build_mask_image(cam_masks):
    """Binary exclusion-mask raster: 255 = active detection area, 0 = masked.

    Only GLOBAL masks (no ``labels`` filter) are baked in — the motion gate
    reads this image and has no label context, so a mask scoped to
    {"person"} must not suppress motion. Labeled masks are evaluated per
    detection in :func:`filter_masked`.
    """
    if not cam_masks:
        return None
    mask = np.ones((CANVAS_H, CANVAS_W), dtype=np.uint8) * 255
    _fill(mask, [p for p in cam_masks if not (isinstance(p, dict) and p.get("labels"))], 0)
    return mask


def build_zone_image(cam_zones):
    """Inclusion-zone raster, inverse of the mask: 0 = outside, 255 = inside.

    ``None`` when no GLOBAL zone is configured — even if label-scoped zones
    exist, the motion path has no label context and must treat the whole
    frame as active.
    """
    global_zones = [z for z in (cam_zones or []) if not (isinstance(z, dict) and z.get("labels"))]
    if not global_zones:
        return None
    zone = np.zeros((CANVAS_H, CANVAS_W), dtype=np.uint8)
    _fill(zone, global_zones, 255)
    return zone


def _resize_to_frame(image, w_f: int, h_f: int):
    """Nearest-neighbour fit of a canvas raster onto the frame, or None."""
    if image is None:
        return None
    h_i, w_i = image.shape[:2]
    if (h_i, w_i) == (h_f, w_f):
        return image
    return cv2.resize(image, (w_f, h_f), interpolation=cv2.INTER_NEAREST)


def _centre(det, w_f: int, h_f: int) -> tuple:
    x1, y1, x2, y2 = det.bbox
    return (
        max(0, min(w_f - 1, (x1 + x2) // 2)),
        max(0, min(h_f - 1, (y1 + y2) // 2)),
    )


def filter_masked(detections: list, frame, cam_masks, mask_image, camera_id: str = "") -> list:
    """Drop detections whose bbox-centre lands inside a masked region.

    Two-stage:
      1. Global masks are pre-baked into ``mask_image`` and tested with a
         single pixel lookup — fast path, applies to every label.
      2. Labeled masks are evaluated per detection so a mask scoped to
         {"person"} only suppresses that label and lets cats/birds
         through the same area.
    """
    if not detections:
        return detections
    h_f, w_f = frame.shape[:2]
    mask_resized = _resize_to_frame(mask_image, w_f, h_f)
    cam_masks = cam_masks or []
    labeled = [m for m in cam_masks if isinstance(m, dict) and m.get("labels")]
    kept: list = []
    for d in detections:
        cx, cy = _centre(d, w_f, h_f)
        if mask_resized is not None and mask_resized[cy, cx] == 0:
            log.debug(
                "[cam:%s] Detection '%s' (%.0f%%) suppressed by global mask at (%d,%d)",
                camera_id,
                d.label,
                d.score * 100,
                cx,
                cy,
            )
            continue
        dropped = False
        for m in labeled:
            if d.label not in m.get("labels", []):
                continue
            src_w = int(m.get("source_w") or CANVAS_W)
            src_h = int(m.get("source_h") or CANVAS_H)
            if point_in_poly(cx, cy, flatten_poly_points(m), w_f, h_f, src_w, src_h):
                log.debug(
                    "[cam:%s] Detection '%s' (%.0f%%) suppressed by label-mask",
                    camera_id,
                    d.label,
                    d.score * 100,
                )
                dropped = True
                break
        if not dropped:
            kept.append(d)
    return kept


def _zone_buckets(cam_zones) -> tuple:
    """``(labeled, global_polys)`` — full polygon dicts, not just points.

    The dicts are needed because the surviving detection is tagged with the
    matched zone's trigger flags (save_photo / save_video / send_telegram).
    """
    labeled: dict = {}
    global_polys: list = []
    for z in cam_zones:
        if not isinstance(z, dict):
            continue
        pts = z.get("points") or []
        if not isinstance(pts, list) or len(pts) < 3:
            continue
        zlabels = z.get("labels") or []
        if not zlabels:
            global_polys.append(z)
        else:
            for label in zlabels:
                labeled.setdefault(label, []).append(z)
    return labeled, global_polys


def _matching_zone(cx: int, cy: int, w_f: int, h_f: int, label_zones, global_polys, in_global):
    """The most specific zone containing the centre, or ``None``.

    Label-scoped zones win over global ones: the operator asked for "person
    only inside THIS polygon", so that polygon's trigger flags are the ones
    the event must carry.
    """
    for z in label_zones:
        z_sw = int(z.get("source_w") or CANVAS_W)
        z_sh = int(z.get("source_h") or CANVAS_H)
        if point_in_poly(cx, cy, flatten_poly_points(z), w_f, h_f, z_sw, z_sh):
            return z
    if not in_global:
        return None
    # The prebaked raster only says "inside SOMETHING" — locate the polygon
    # itself so its flags can be forwarded.
    for z in global_polys:
        z_sw = int(z.get("source_w") or CANVAS_W)
        z_sh = int(z.get("source_h") or CANVAS_H)
        if point_in_poly(cx, cy, flatten_poly_points(z), w_f, h_f, z_sw, z_sh):
            return z
    return None


def filter_zoned(detections: list, frame, cam_zones, zone_image, camera_id: str = "") -> list:
    """Keep only detections whose bbox-centre lands inside an applicable
    inclusion zone.

    Per-label semantics:
      - If a label has at least one applicable zone (global or its label
        specifically named), the detection MUST be inside one of them.
      - If no zone applies to that label, the detection passes through
        (this lets the user define "person only inside this polygon"
        without restricting cat/bird).
    """
    if not detections:
        return detections
    cam_zones = cam_zones or []
    if not cam_zones:
        return detections  # no zones at all → unrestricted
    h_f, w_f = frame.shape[:2]
    zone_resized = _resize_to_frame(zone_image, w_f, h_f)
    labeled, global_polys = _zone_buckets(cam_zones)
    kept: list = []
    for d in detections:
        cx, cy = _centre(d, w_f, h_f)
        global_applies = zone_resized is not None
        label_zones = labeled.get(d.label, [])
        if not global_applies and not label_zones:
            kept.append(d)  # no zone targets this label at all
            continue
        matched = _matching_zone(
            cx,
            cy,
            w_f,
            h_f,
            label_zones,
            global_polys,
            global_applies and zone_resized[cy, cx] > 0,
        )
        if matched is None:
            log.debug(
                "[cam:%s] Detection '%s' (%.0f%%) outside applicable zones at (%d,%d)",
                camera_id,
                d.label,
                d.score * 100,
                cx,
                cy,
            )
            continue
        d.zone_flags = {
            "save_photo": bool(matched.get("save_photo", True)),
            "save_video": bool(matched.get("save_video", True)),
            "send_telegram": bool(matched.get("send_telegram", True)),
        }
        kept.append(d)
    return kept


class MaskZoneCache:
    """One owner's compiled mask + zone rasters.

    Rebuilds only when the polygon signature changes, so the per-frame path
    stays a pixel lookup. Never shared between the alarm loop and a
    diagnostic: a cache is mutable state, and the whole reason this module
    exists is that the panel was mutating the loop's.
    """

    def __init__(self) -> None:
        self.mask_image = None
        self.mask_sig: str | None = None
        self.zone_image = None
        self.zone_sig: str | None = None

    def refresh_mask(self, cam_masks) -> bool:
        """Rebuild the mask raster if the config changed. True when rebuilt.

        The image is assigned BEFORE the signature: a reader that sees the
        new signature must never be able to read the old image behind it.
        """
        sig = signature(cam_masks or [])
        if sig == self.mask_sig:
            return False
        self.mask_image = build_mask_image(cam_masks or [])
        self.mask_sig = sig
        return True

    def refresh_zone(self, cam_zones) -> bool:
        """Rebuild the zone raster if the config changed. True when rebuilt."""
        sig = signature(cam_zones or [])
        if sig == self.zone_sig:
            return False
        self.zone_image = build_zone_image(cam_zones or [])
        self.zone_sig = sig
        return True

    def masked(self, detections: list, frame, cam_masks, camera_id: str = "") -> list:
        self.refresh_mask(cam_masks)
        return filter_masked(detections, frame, cam_masks, self.mask_image, camera_id)

    def zoned(self, detections: list, frame, cam_zones, camera_id: str = "") -> list:
        self.refresh_zone(cam_zones)
        return filter_zoned(detections, frame, cam_zones, self.zone_image, camera_id)
