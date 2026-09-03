"""Zone polygons: inferring the canvas a stored polygon was drawn on."""

from __future__ import annotations

import logging

log = logging.getLogger("app.settings.migrations")


_ZONE_CANVASES = ((640, 360), (960, 540), (1280, 720), (1920, 1080), (2560, 1440))


def _infer_zone_canvas(points) -> tuple[int, int] | None:
    """Smallest editor canvas that could hold every point, or ``None``.

    Only ever consulted for a polygon with NO ``source_w``/``source_h``
    stamp, which today is read as 1280x720 by the runtime and as the
    camera's current preview resolution by the browser — two different
    guesses, neither of them recorded. Bounding the points is at least a
    guess made from the data.
    """
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    if not xs or not ys:
        return None
    need_w, need_h = max(xs) + 1, max(ys) + 1
    for w, h in _ZONE_CANVASES:
        if need_w <= w and need_h <= h:
            return w, h
    return None


def migrate_zone_source_space(data: dict) -> None:
    """Stamp the drawing canvas onto polygons that never recorded one.

    THE BUG: ``mask_zones.point_in_poly`` scales a detection's centre into
    the polygon's own space using ``source_w``/``source_h``. Polygons
    drawn before that stamp existed fall back to the hard-coded
    1280x720 canvas — but the Werkstatt zone's own coordinates top out at
    636x356, i.e. it was drawn at 640x360. The gate therefore probed
    y=468 on a polygon that ends at y=356, so EVERY person in the lower
    part of the frame was rejected as "outside applicable zones". A
    security camera that detected a person at 87 % and never reported it.

    Verified against the real data: at the inferred 640x360 the two
    logged 86/87 % person centres land INSIDE, while a genuine 21 %
    detection in the top corner correctly stays outside.

    Deliberately NOT done instead: changing the 1280x720 fallback
    constant. That same constant also governs EXCLUSION MASKS, so moving
    it would shift masks on cameras that work correctly today and could
    open a new blind spot on a security camera. Recording what each
    polygon was actually drawn on is the repair; re-interpreting a shared
    constant is not.
    """
    from ...mask_zones import flatten_poly_points, point_xy

    stamped = 0
    for cam in data.get("cameras") or []:
        if not isinstance(cam, dict):
            continue
        for key in ("zones", "masks"):
            for poly in cam.get(key) or []:
                if not isinstance(poly, dict) or poly.get("source_w") or poly.get("source_h"):
                    continue
                pts = [point_xy(p) for p in flatten_poly_points(poly)]
                canvas = _infer_zone_canvas(pts)
                if not canvas:
                    continue
                poly["source_w"], poly["source_h"] = canvas
                stamped += 1
                log.warning(
                    "[migration] %s: %s ohne Zeichenraum — auf %dx%d gestempelt "
                    "(bitte im Editor prüfen)",
                    cam.get("id"),
                    key,
                    canvas[0],
                    canvas[1],
                )
    if stamped:
        log.warning(
            "[migration] %d Polygon(e) nachgestempelt — vorher wurden sie gegen "
            "1280x720 geprüft und konnten Treffer fälschlich verwerfen",
            stamped,
        )
