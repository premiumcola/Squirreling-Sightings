"""Shared SAHI-style tiling / motion-ROI detection helpers.

Extracted from routes/_sim_tiling.py (C3) so BOTH the live-detect simulator
(routes/coral_test_detection.py) and the PRODUCTION pipeline
(camera_runtime/_main_loop.py, D2) import the same tiling + NMS code — no
duplicate implementation.

Rationale (B-experiment, storage/_diag/substream_test_*.md): full-frame
inference letterboxes the whole HD frame to the model's ~300 px input and is
blind to small/distant subjects (dog 0.00); a 2×2 / 3×3 tile pass — or a crop
of the motion ROI — feeds each region to the model at a much higher effective
resolution and recovers them (dog 0.76). Tiling is expensive, so production
runs it only on the escalated wildlife-low + coherent-motion case (D1/D2).
"""

from __future__ import annotations

import logging
import math

import cv2
import numpy as np

from .bbox_utils import iou

log = logging.getLogger(__name__)

VALID_MODES = ("off", "roi", "2x2", "3x3")
# Fallback for a mode that is set but unrecognised — `roi` is the only mode
# whose magnification scales with how small the subject is.
FALLBACK_MODE = "roi"
TILE_OVERLAP = 0.15
# Minimum linear zoom a region has to reach before it is worth an inference.
# 1.5 is deliberately modest: it rejects the "crop is basically the frame"
# case without splitting crops that already help.
DEFAULT_MIN_MAGNIFICATION = 1.5


def normalise_mode(mode) -> str:
    """Map a configured ``roi_mode`` onto :data:`VALID_MODES`.

    Unset / empty stays ``off`` — that is the schema default and means the
    operator has not switched the rescue on. A value that is *set but not
    recognised* used to read exactly like ``off``: the rescue was disabled
    silently and nothing said so. It now warns and falls back to ``roi``.
    """
    if mode is None:
        return "off"
    text = str(mode).strip().lower()
    if not text:
        return "off"
    if text in VALID_MODES:
        return text
    log.warning("[det] unknown roi_mode %r — falling back to %r", mode, FALLBACK_MODE)
    return FALLBACK_MODE


def magnification(frame_w: int, frame_h: int, region) -> float:
    """Linear zoom of ``region`` relative to the full-frame pass.

    Both passes letterbox into the same square model input, so the gain is
    just the ratio of the longer edges: a 2560x1440 frame cropped to
    800x600 reaches the model at 2560/800 = 3.2x the linear resolution the
    full-frame pass gave it. A 2x2 tile of the same frame reaches only
    ~1.74x — which is why `roi` is the mode that matters for small
    subjects, and why a crop that barely shrinks the frame is an
    inference spent for nothing.
    """
    x1, y1, x2, y2 = region
    longest = max(1, x2 - x1, y2 - y1)
    return max(frame_w, frame_h) / float(longest)


def split_for_magnification(
    region,
    frame_w: int,
    frame_h: int,
    min_magnification: float = DEFAULT_MIN_MAGNIFICATION,
    max_parts: int = 4,
):
    """Cut ``region`` into overlapping parts until each one actually zooms.

    A motion box that spans a third of the frame produces an ROI crop with
    a magnification near 1.0 — the subject arrives at the model at the same
    resolution the full-frame pass already showed it, so the rescue cannot
    possibly find anything new. Splitting that crop is what turns a wasted
    pass into a zoom. Capped at ``max_parts`` so the added CPU inference
    cost per rescue stays bounded and predictable.
    """
    x1, y1, x2, y2 = region
    cw, ch = x2 - x1, y2 - y1
    if cw <= 0 or ch <= 0:
        return []
    if min_magnification <= 0:
        return [region]
    if magnification(frame_w, frame_h, region) >= min_magnification:
        return [region]
    # Longest edge a part may have to still reach the requested zoom.
    limit = max(1.0, max(frame_w, frame_h) / float(min_magnification))
    # tile_regions pads every part by `overlap` on each side, so a 1/n slice
    # is ~(1 + 2·overlap)/n of the crop, not 1/n.
    span = 1.0 + 2.0 * TILE_OVERLAP
    gx = max(1, int(math.ceil(cw * span / limit)))
    gy = max(1, int(math.ceil(ch * span / limit)))
    while gx * gy > max_parts and gx * gy > 1:
        if gx >= gy:
            gx -= 1
        else:
            gy -= 1
    if gx * gy <= 1:
        return [region]
    return [(x1 + a, y1 + b, x1 + c, y1 + d) for a, b, c, d in tile_regions(cw, ch, gx, gy)]


def tile_regions(w: int, h: int, gx: int, gy: int, overlap: float = TILE_OVERLAP):
    """Split a W×H frame into gx·gy overlapping tile rectangles."""
    tw, th = w / gx, h / gy
    ox, oy = int(tw * overlap), int(th * overlap)
    regions = []
    for iy in range(gy):
        for ix in range(gx):
            x1 = max(0, int(ix * tw) - ox)
            y1 = max(0, int(iy * th) - oy)
            x2 = min(w, int((ix + 1) * tw) + ox)
            y2 = min(h, int((iy + 1) * th) + oy)
            regions.append((x1, y1, x2, y2))
    return regions


def detect_region(detector, frame, region, threshold):
    """Run the detector on one cropped region; map boxes back to frame coords.
    detect_frame_raw upscales the crop to the model input internally, so a
    small subject occupies more model-input pixels than in the full frame."""
    x1, y1, x2, y2 = region
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return []
    out = []
    for d in detector.detect_frame_raw(crop, threshold=threshold):
        bx1, by1, bx2, by2 = d.bbox
        d.bbox = (bx1 + x1, by1 + y1, bx2 + x1, by2 + y1)
        out.append(d)
    return out


def nms_merge(dets, iou_thresh: float = 0.45):
    """Greedy per-label NMS — keeps the highest-scoring box of each cluster
    so a subject straddling a tile seam isn't double-counted."""
    kept = []
    for d in sorted(dets, key=lambda x: x.score, reverse=True):
        if any(d.label == k.label and iou(d.bbox, k.bbox) >= iou_thresh for k in kept):
            continue
        kept.append(d)
    return kept


def prep_gray(frame):
    """Grayscale + blur, matching the motion gate's preprocessing."""
    return cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (15, 15), 0)


def motion_bbox(prev_gray, gray, frame_area: float, min_area_frac: float = 0.0008):
    """Frame-diff motion bbox (mirrors camera_runtime/_motion.py's
    absdiff→threshold→dilate→contour recipe, at a low area floor so small
    subjects survive). Returns (x, y, w, h) or None."""
    if prev_gray is None or gray is None or prev_gray.shape != gray.shape:
        return None
    diff = cv2.absdiff(prev_gray, gray)
    _, thresh = cv2.threshold(diff, 28, 255, cv2.THRESH_BINARY)
    thresh = cv2.dilate(thresh, None, iterations=2)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    floor = max(1.0, frame_area * min_area_frac)
    big = [c for c in contours if cv2.contourArea(c) >= floor]
    if not big:
        return None
    return tuple(int(v) for v in cv2.boundingRect(np.concatenate(big)))


def roi_regions(w: int, h: int, motion_box, min_magnification: float):
    """Padded crop around the motion box, split until it really magnifies."""
    if not motion_box:
        return []
    mx, my, mw, mh = motion_box
    pad = int(0.25 * max(mw, mh)) + 8
    rx1, ry1 = max(0, mx - pad), max(0, my - pad)
    rx2, ry2 = min(w, mx + mw + pad), min(h, my + mh + pad)
    if rx2 <= rx1 or ry2 <= ry1:
        return []
    return split_for_magnification((rx1, ry1, rx2, ry2), w, h, min_magnification)


def _diag(mode, regions, w, h, tile_hits, raw, merged, min_magnification):
    """Diagnostics for one tiled_detect pass.

    ``magnification`` and ``crop_px`` are the numbers the whole small-object
    category hangs on and were previously invisible: whether an ROI crop
    zoomed 8x or not at all depended entirely on the motion box size and
    was reported nowhere, so the mode could be neither trusted nor tuned.
    """
    return {
        "mode": mode,
        "tiles": len(regions),
        "raw": raw,
        "merged": merged,
        "tile_hits": tile_hits,
        "magnification": [round(magnification(w, h, r), 2) for r in regions],
        "crop_px": [(r[2] - r[0], r[3] - r[1]) for r in regions],
        "min_magnification": float(min_magnification),
    }


def tiled_detect(
    detector,
    frame,
    mode: str,
    threshold: float = 0.20,
    motion_box=None,
    min_magnification: float = DEFAULT_MIN_MAGNIFICATION,
    full_dets=None,
):
    """Hybrid full-frame + tiling/ROI detection.

    Returns (merged_detections, diag) where diag carries the SAHI counters.
    mode: 'off' (full only) | '2x2' | '3x3' | 'roi' (motion bbox crop).
    A full-frame pass is always part of the merge — pass ``full_dets`` to
    reuse one the caller has already run instead of paying for a second
    identical inference (the live loop always has one in hand).
    """
    h, w = frame.shape[:2]
    mode = normalise_mode(mode)
    if full_dets is not None:
        full = list(full_dets)
    else:
        full = list(detector.detect_frame_raw(frame, threshold=threshold))
    if mode == "off":
        return full, _diag("off", [], w, h, [], len(full), len(full), min_magnification)

    if mode == "2x2":
        regions = tile_regions(w, h, 2, 2)
    elif mode == "3x3":
        regions = tile_regions(w, h, 3, 3)
    else:  # roi
        regions = roi_regions(w, h, motion_box, min_magnification)

    tile_hits = []
    tiled = []
    for r in regions:
        rd = detect_region(detector, frame, r, threshold)
        tile_hits.append(len(rd))
        tiled.extend(rd)
    raw_all = full + tiled
    merged = nms_merge(raw_all)
    return merged, _diag(
        mode, regions, w, h, tile_hits, len(raw_all), len(merged), min_magnification
    )
